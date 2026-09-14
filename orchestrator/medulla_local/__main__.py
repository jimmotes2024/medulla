"""Local service and explicit worker/operator commands. No system-wide setup."""

import argparse
import json
import os
import signal
import sys
import threading
from pathlib import Path

from .client import Client
from .local_worker import attach, run_once
from .security import StateLock, credential, private_write
from .server import Server
from .store import Store


def main():
    parser = argparse.ArgumentParser(description='Medulla Local — explicit worker orchestration')
    sub = parser.add_subparsers(dest='command', required=True)
    serve = sub.add_parser('serve', help='Start a loopback-only coordinator')
    serve.add_argument('--state-dir', default='.medulla-local')
    serve.add_argument('--port', type=int, default=0)
    serve.add_argument('--local-worker', action='store_true', help='Enable the deterministic text worker (no model)')
    enroll = sub.add_parser('enroll', help='Enroll a new worker through the operator API')
    enroll.add_argument('--url', required=True)
    enroll.add_argument('--admin-key-file', required=True)
    enroll.add_argument('--name', required=True)
    enroll.add_argument('--provider', required=True)
    enroll.add_argument('--out', required=True, help='New private worker token file')
    worker = sub.add_parser('worker-once', help='Run one task with the built-in deterministic text adapter')
    worker.add_argument('--url', required=True)
    worker.add_argument('--token-file', required=True)
    call = sub.add_parser('call', help='Call an API operation with JSON from stdin')
    call.add_argument('--url', required=True)
    call.add_argument('--token-file', required=True)
    call.add_argument('path')
    launch = sub.add_parser('open-url', help='Print a single-use console link (expires in 60 seconds)')
    launch.add_argument('--state-dir', default='.medulla-local')
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == 'serve':
        directory = Path(args.state_dir).resolve()
        lock = StateLock(directory)
        server = None
        try:
            store = Store(directory / 'coordinator.sqlite3')
            server = Server(store, credential(directory / 'operator.key'), args.port)
            (directory / 'endpoint.json').write_text(json.dumps({'url': server.origin, 'pid': os.getpid()}))
            if args.local_worker:
                attach(server, directory)
            def stop(_signal, _frame):
                server.stopping.set()
                threading.Thread(target=server.shutdown, daemon=True).start()
            signal.signal(signal.SIGINT, stop)
            signal.signal(signal.SIGTERM, stop)
            print('Medulla Local: ' + server.origin, flush=True)
            print('Operator key file: ' + str(directory / 'operator.key'), flush=True)
            print('External agent sessions: disconnected', flush=True)
            server.serve_forever(poll_interval=0.25)
        finally:
            if server:
                server.stopping.set()
                server.server_close()
            lock.close()
    elif args.command == 'open-url':
        directory = Path(args.state_dir).resolve()
        endpoint = json.loads((directory/'endpoint.json').read_text())
        client = Client(endpoint['url'], (directory/'operator.key').read_text().strip())
        print(client.post('/api/open-ticket')['url'])
    elif args.command == 'enroll':
        destination = Path(args.out)
        if destination.exists() or destination.is_symlink():
            raise ValueError('Credential output already exists; choose a new file')
        client = Client(args.url, Path(args.admin_key_file).read_text().strip())
        result = client.post('/api/agents', {'name': args.name, 'provider': args.provider})
        private_write(destination, result['token'])
        print(json.dumps({'agent_id': result['id'], 'credential_file': str(destination)}))
    elif args.command == 'worker-once':
        client = Client(args.url, Path(args.token_file).read_text().strip())
        print(json.dumps({'executed': run_once(client), 'adapter': 'local-text'}))
    else:
        client = Client(args.url, Path(args.token_file).read_text().strip())
        print(json.dumps(client.post(args.path, json.load(sys.stdin)), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print('Medulla: ' + str(exc), file=sys.stderr)
        sys.exit(1)
