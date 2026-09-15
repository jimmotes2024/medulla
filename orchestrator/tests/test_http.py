"""The real loopback server: HTTP security and a disposable worker handoff."""

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from medulla_local.client import Client
from medulla_local.local_worker import run_once
from medulla_local.server import Server
from medulla_local.store import Store
from test_sources import write_cockpit


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'db')
        self.server = Server(self.store, 'operator-secret-test-value')
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval':0.01}, daemon=True)
        self.thread.start()
        self.agent, self.key = self.store.enroll('Disposable worker', 'test')
        self.admin = Client(self.server.origin, self.server.admin_token)
        self.worker = Client(self.server.origin, self.key)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.tmp.cleanup()

    def request(self, method, path, data=None, token=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        body = None if data is None else json.dumps(data)
        hdr = {} if data is None else {'Content-Type':'application/json'}
        if token:
            hdr['Authorization'] = 'Bearer ' + token
        hdr.update(headers or {})
        connection.request(method, path, body, hdr)
        response = connection.getresponse()
        status, response_headers, raw = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, response_headers, raw

    def test_static_public_but_all_records_private(self):
        self.assertEqual(self.request('GET','/')[0],200)
        for path in ('/api/state','/api/events','/api/export'):
            self.assertEqual(self.request('GET',path)[0],401)
            self.assertEqual(self.request('GET',path,token=self.key)[0],401)
            self.assertEqual(self.request('GET',path,token=self.server.admin_token)[0],200)

    def test_rebinding_host_and_foreign_origin_rejected(self):
        self.assertEqual(self.request('GET','/api/state',token=self.server.admin_token,headers={'Host':'attacker.example'})[0],403)
        self.assertEqual(self.request('POST','/api/projects',{'name':'bad'},self.server.admin_token,{'Origin':'https://attacker.example'})[0],403)

    def test_cookie_requires_origin_for_mutation(self):
        code, headers, _ = self.request('POST','/api/session',{'token':self.server.admin_token},headers={'Origin':self.server.origin})
        self.assertEqual(code,200)
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        self.assertEqual(self.request('GET','/api/state',headers={'Cookie':cookie})[0],200)
        self.assertEqual(self.request('POST','/api/projects',{'name':'bad'},headers={'Cookie':cookie})[0],401)
        self.assertEqual(self.request('POST','/api/projects',{'name':'good'},headers={'Cookie':cookie,'Origin':self.server.origin})[0],200)
        self.assertEqual(self.request('POST','/api/logout',{},headers={'Cookie':cookie,'Origin':self.server.origin})[0],200)
        self.assertEqual(self.request('GET','/api/state',headers={'Cookie':cookie})[0],401)

    def test_login_requires_origin_and_has_rate_limit(self):
        self.assertEqual(self.request('POST','/api/session',{'token':self.server.admin_token})[0],403)
        for _ in range(10):
            self.assertEqual(self.request('POST','/api/session',{'token':'wrong'},headers={'Origin':self.server.origin})[0],401)
        self.assertEqual(self.request('POST','/api/session',{'token':'wrong'},headers={'Origin':self.server.origin})[0],429)

    def test_worker_cannot_perform_operator_mutations(self):
        for path, data in [('/api/projects',{'name':'bad'}),('/api/agents',{'name':'bad','provider':'bad'}),
                           ('/api/tasks/action',{'task_id':'x','action':'approve'}),('/api/pause',{'paused':False}),
                           ('/api/agents/revoke',{'agent_id':self.agent})]:
            self.assertEqual(self.request('POST',path,data,self.key)[0],400)

    def test_operator_cannot_impersonate_worker(self):
        self.assertEqual(self.request('POST','/api/worker/claim',{},self.server.admin_token)[0],400)

    def test_invalid_json_content_type_fields_and_body_size(self):
        self.assertEqual(self.request('POST','/api/projects',{'name':'x'},self.server.admin_token,{'Content-Type':'text/plain'})[0],400)
        self.assertEqual(self.request('POST','/api/projects',[],self.server.admin_token)[0],400)
        self.assertEqual(self.request('POST','/api/projects',{'name':42},self.server.admin_token)[0],400)
        self.assertEqual(self.request('POST','/api/projects',{'name':'x','unexpected':1},self.server.admin_token)[0],400)
        self.assertEqual(self.request('POST','/api/projects',{'name':'x'},self.server.admin_token,{'Content-Length':'999999999'})[0],400)

    def test_secret_and_traversal_files_are_never_served(self):
        for path in ('/operator.key','/../operator.key','/%2e%2e/AGENTS.md','/coordinator.sqlite3'):
            self.assertEqual(self.request('GET',path,token=self.server.admin_token)[0],404)

    def test_security_headers_and_no_cors(self):
        _, headers, _ = self.request('GET','/')
        self.assertIn("script-src 'self'",headers['Content-Security-Policy'])
        self.assertNotIn('unsafe-inline',headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Frame-Options'],'DENY')
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertNotIn('Access-Control-Allow-Origin',headers)

    def test_port_reuse_cannot_replace_an_active_listener(self):
        with self.assertRaises(OSError):
            Server(self.store,'other-test-key',self.server.server_port)

    def test_real_worker_handoff_approval_review_and_dependency(self):
        project = self.admin.post('/api/projects',{'name':'Disposable protocol rehearsal'})['id']
        first = self.admin.post('/api/tasks',{'project_id':project,'title':'Fingerprint','instruction':'Real bounded text analysis','agent_id':self.agent})['id']
        second = self.admin.post('/api/tasks',{'project_id':project,'title':'Verify','instruction':'Verify accepted dependency','agent_id':self.agent,'dependencies':[first],'requires_approval':True})['id']
        self.assertTrue(run_once(self.worker))
        self.assertFalse(run_once(self.worker))
        state = self.store.snapshot()
        artifact = next(t for t in state['tasks'] if t['id']==first)['artifacts'][0]
        parsed = json.loads(artifact['content'])
        self.assertEqual(parsed['instruction_words'],4)
        self.assertEqual(parsed['model_calls'],0)
        self.admin.post('/api/tasks/action',{'task_id':first,'action':'accept','artifact_id':artifact['id']})
        self.assertFalse(run_once(self.worker))
        self.admin.post('/api/tasks/action',{'task_id':second,'action':'approve'})
        self.assertTrue(run_once(self.worker))
        second_artifact = next(t for t in self.store.snapshot()['tasks'] if t['id']==second)['artifacts'][0]
        self.assertTrue(json.loads(second_artifact['content'])['accepted_dependencies'][0]['matches'])
        kinds = [e['kind'] for e in self.store.export()['events'] if e['task_id']==first]
        self.assertEqual(kinds,['task.created','attempt.claimed','attempt.ack','attempt.start','attempt.complete','task.accept'])

    def test_worker_revocation_takes_effect_over_http(self):
        self.store.revoke(self.agent)
        self.assertEqual(self.request('POST','/api/worker/claim',{},self.key)[0],401)

    def test_console_launch_ticket_is_single_use_and_expires(self):
        import time
        issued = self.admin.post('/api/open-ticket')
        self.assertNotIn(self.server.admin_token,issued['url'])
        ticket = issued['url'].split('#ticket=')[1]
        self.assertEqual(self.request('POST','/api/session',{'ticket':ticket},headers={'Origin':self.server.origin})[0],200)
        self.assertEqual(self.request('POST','/api/session',{'ticket':ticket},headers={'Origin':self.server.origin})[0],401)
        expired = self.admin.post('/api/open-ticket')['url'].split('#ticket=')[1]
        self.server.tickets[expired] = time.monotonic()-1
        self.assertEqual(self.request('POST','/api/session',{'ticket':expired},headers={'Origin':self.server.origin})[0],401)
        self.assertEqual(self.request('POST','/api/open-ticket',{},self.key)[0],400)

    def test_protocol_refuses_worker_identity_injection(self):
        self.assertEqual(self.request('POST','/api/worker/attempt',{'agent_id':'operator','attempt_id':'x','operation':'start'},self.key)[0],400)

    def test_connected_project_is_private_and_never_enters_execution_queue(self):
        root = Path(self.tmp.name)/'example-panel';write_cockpit(root)
        self.server.sources.connect(root,'Example project')
        status, _, raw = self.request('GET','/api/state',token=self.server.admin_token)
        self.assertEqual(status,200)
        state = json.loads(raw)
        self.assertEqual(state['observed']['projects'][0]['tasks'][0]['id'],'EXAMPLE-1')
        self.assertEqual(state['tasks'],[])
        self.assertEqual(state['projects'],[])
        self.assertIsNone(self.worker.post('/api/worker/claim')['assignment'])
        self.assertEqual(self.request('GET','/api/state',token=self.key)[0],401)
        self.assertEqual(self.request('POST','/api/tasks/action',{'task_id':'EXAMPLE-1','action':'approve'},self.server.admin_token)[0],400)
        self.assertEqual(self.request('GET','/api/source-file?path=tasks/TASKS.v1.json',token=self.server.admin_token)[0],404)

    def test_broken_project_connection_does_not_hide_local_assignments(self):
        (Path(self.tmp.name)/'sources.json').write_text('invalid')
        self.admin.post('/api/projects',{'name':'Local work'})
        status, _, raw = self.request('GET','/api/state',token=self.server.admin_token)
        self.assertEqual(status,200)
        state = json.loads(raw)
        self.assertEqual(state['projects'][0]['name'],'Local work')
        self.assertIsNotNone(state['observed']['error'])


if __name__ == '__main__':
    unittest.main()
