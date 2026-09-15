"""Loopback-only HTTP boundary with separate operator and worker authorization."""

import hmac
import json
import secrets
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from . import __version__
from .store import Problem
from .workers import Workers
from .sources import Sources

WEB = Path(__file__).with_name('web')
ASSETS = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
          '/style.css': ('style.css', 'text/css'), '/favicon.svg': ('favicon.svg', 'image/svg+xml')}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # Permit a same-port restart after shutdown; this is not SO_REUSEPORT and
    # cannot replace an active listener. The state-directory lock still applies.
    allow_reuse_address = True

    def __init__(self, store, admin_token, port=0):
        self.store, self.admin_token = store, admin_token
        self.workers = Workers(store)
        self.sources = Sources(store.path.parent)
        self.session_token = secrets.token_urlsafe(32)
        self.login_lock, self.failed_logins = threading.Lock(), []
        self.tickets = {}
        self.local_agent_id = None
        self.stopping = threading.Event()
        self.slots = threading.BoundedSemaphore(24)
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'MedullaLocal'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_args):
        pass  # Request URLs, instructions and credentials never enter access logs.

    def reply(self, status, data, mime='application/json', headers=None):
        body = json.dumps(data).encode() if mime == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', mime + ('; charset=utf-8' if mime.startswith('text/') else ''))
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def boundary(self):
        if self.headers.get('Host') != urlsplit(self.server.origin).netloc:
            self.reply(403, {'error': 'Invalid host'})
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin != self.server.origin:
            self.reply(403, {'error': 'Cross-origin request refused'})
            return False
        return True

    def auth(self):
        bearer = self.headers.get('Authorization', '')
        if bearer.startswith('Bearer '):
            token = bearer[7:]
            if hmac.compare_digest(token, self.server.admin_token):
                return 'operator'
            return self.server.store.principal(token)
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie', ''))
        except Exception:
            return None
        value = cookies.get('medulla_session')
        if value and hmac.compare_digest(value.value, self.server.session_token):
            if self.command != 'GET' and self.headers.get('Origin') != self.server.origin:
                return None
            return 'operator'
        return None

    def do_GET(self):
        if not self.boundary():
            return
        path = urlsplit(self.path).path
        if path in ASSETS:
            file, mime = ASSETS[path]
            return self.reply(200, (WEB / file).read_bytes(), mime)
        if self.auth() != 'operator':
            return self.reply(401, {'error': 'Operator sign-in required'})
        if path == '/api/state':
            return self.reply(200, {**self.server.store.snapshot(), 'version': __version__,
                                    'local_agent_id': self.server.local_agent_id,
                                    'observed': self.server.sources.snapshot()})
        if path == '/api/export':
            return self.reply(200, {**self.server.store.export(), 'version': __version__},
                              headers={'Content-Disposition': 'attachment; filename="medulla-records.json"'})
        if path == '/api/events':
            try:
                after = int(parse_qs(urlsplit(self.path).query).get('after', ['0'])[0])
                if after < 0:
                    raise ValueError()
            except ValueError:
                return self.reply(400, {'error': 'Invalid event cursor'})
            return self.reply(200, self.server.store.events(after))
        self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.boundary():
            return
        try:
            if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
                raise Problem('Use a JSON request with a Content-Length')
            length = int(self.headers.get('Content-Length', '0'))
            if length < 2 or length > 262144:
                raise Problem('Request body must be 2–262144 bytes')
            body = self.rfile.read(length)
            if len(body) != length:
                raise Problem('Incomplete request')
            data = json.loads(body)
            if not isinstance(data, dict):
                raise Problem('Expected a JSON object')
            path = urlsplit(self.path).path
            if path == '/api/session':
                return self.login(data)
            actor = self.auth()
            if actor is None:
                return self.reply(401, {'error': 'Authentication required'})
            result = self.route(path, data, actor)
            self.reply(200, result)
        except (Problem, TypeError, ValueError) as exc:
            self.reply(400, {'error': str(exc) if isinstance(exc, Problem) else 'Invalid request fields'})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            self.reply(500, {'error': 'Operation failed; inspect local service health'})

    def login(self, data):
        if self.headers.get('Origin') != self.server.origin:
            return self.reply(403, {'error': 'Same-origin sign-in required'})
        with self.server.login_lock:
            now = time.monotonic()
            self.server.failed_logins = [t for t in self.server.failed_logins if now - t < 60]
            if len(self.server.failed_logins) >= 10:
                return self.reply(429, {'error': 'Too many attempts; wait a minute'})
            token, ticket = data.get('token'), data.get('ticket')
            valid = isinstance(token, str) and hmac.compare_digest(token, self.server.admin_token)
            if isinstance(ticket, str):
                expires = self.server.tickets.pop(ticket, 0)
                valid = expires > now
            if not valid:
                self.server.failed_logins.append(now)
                return self.reply(401, {'error': 'Invalid operator key'})
        return self.reply(200, {'signed_in': True}, headers={
            'Set-Cookie': 'medulla_session=' + self.server.session_token + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'})

    def route(self, path, data, actor):
        s, w = self.server.store, self.server.workers
        if path.startswith('/api/worker/'):
            if actor == 'operator':
                raise Problem('Use a scoped worker credential for worker operations')
            if path == '/api/worker/claim':
                return {'assignment': w.claim(actor)}
            if path == '/api/worker/pulse':
                return w.pulse(actor)
            if path == '/api/worker/attempt':
                return w.transition(actor, **data)
        if actor != 'operator':
            raise Problem('This operation requires the operator')
        if path == '/api/open-ticket':
            with self.server.login_lock:
                now = time.monotonic()
                self.server.tickets = {k:v for k,v in self.server.tickets.items() if v>now}
                if len(self.server.tickets) >= 16:
                    raise Problem('Too many unconsumed launch links; wait one minute')
                ticket = secrets.token_urlsafe(32)
                self.server.tickets[ticket] = now + 60
            return {'url': self.server.origin + '/#ticket=' + ticket, 'expires_in': 60}
        if path == '/api/projects':
            return {'id': s.project(**data)}
        if path == '/api/agents':
            aid, token = s.enroll(**data)
            return {'id': aid, 'token': token}
        if path == '/api/agents/revoke':
            s.revoke(**data)
            return {'revoked': True}
        if path == '/api/tasks':
            return {'id': s.create_task(**data)}
        if path == '/api/tasks/action':
            return {'state': s.action(**data)}
        if path == '/api/pause':
            s.pause(**data)
            return {'paused': data['paused']}
        if path == '/api/logout':
            with self.server.login_lock:
                self.server.session_token = secrets.token_urlsafe(32)
                self.server.tickets.clear()
            return {'signed_in': False}
        if path == '/api/rehearsal':
            if not self.server.local_agent_id:
                raise Problem('Start with --local-worker to run a rehearsal')
            pid = s.project('Orchestration rehearsal', 'Isolated local work. No model calls or external sessions.')
            one = s.create_task(pid, 'Prepare a content fingerprint',
                                'Inspect this sample: reliable work has an owner, a receipt, and an artifact.', self.server.local_agent_id)
            two = s.create_task(pid, 'Verify the reviewed handoff',
                                'Inspect the accepted dependency and report its content fingerprint.', self.server.local_agent_id, [one], True)
            return {'project_id': pid, 'task_ids': [one, two]}
        raise Problem('Unknown operation')
