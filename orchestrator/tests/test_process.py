"""Real process boundaries: duplicate service lock, restart, and child worker."""

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from medulla_local.client import Client
from medulla_local.security import StateLock, private_write

ROOT = Path(__file__).resolve().parents[1]


class ProcessTest(unittest.TestCase):
    def test_private_files_refuse_existing_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'key'
            private_write(path,'not-a-real-key')
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):
                private_write(path,'overwrite')
            link = Path(directory) / 'link';link.symlink_to(path)
            with self.assertRaises(FileExistsError):
                private_write(link,'overwrite')

    def test_state_lock_does_not_take_over_running_service(self):
        with tempfile.TemporaryDirectory() as directory:
            first = StateLock(directory)
            try:
                with self.assertRaises(ValueError):
                    StateLock(directory)
            finally:
                first.close()
            second = StateLock(directory);second.close()

    def test_client_refuses_external_endpoints(self):
        for url in ['https://example.com','http://localhost:1234','http://127.0.0.1:12/path','http://user@127.0.0.1:12']:
            with self.assertRaises(ValueError):
                Client(url,'secret')

    def test_child_worker_and_service_restart_preserve_records(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {'PATH':os.defpath,'PYTHONPATH':str(ROOT),'PYTHONUNBUFFERED':'1'}
            state = Path(directory) / 'state'
            command = [sys.executable,'-m','medulla_local','serve','--state-dir',str(state)]
            def start():
                process = subprocess.Popen(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                deadline = time.monotonic()+8
                while time.monotonic()<deadline:
                    endpoint = state / 'endpoint.json'
                    if endpoint.exists():
                        data = json.loads(endpoint.read_text())
                        if data['pid']==process.pid:
                            return process,data['url']
                    if process.poll() is not None:
                        raise AssertionError(process.stderr.read())
                    time.sleep(.03)
                process.terminate();process.wait();raise AssertionError('Service startup timed out')
            process,url = start()
            try:
                token = (state/'operator.key').read_text().strip()
                admin = Client(url,token)
                project = admin.post('/api/projects',{'name':'Process rehearsal'})['id']
                agent = admin.post('/api/agents',{'name':'Child worker','provider':'local-text'})
                key = Path(directory)/'worker.key';private_write(key,agent['token'])
                task = admin.post('/api/tasks',{'project_id':project,'title':'Process proof','instruction':'one two three','agent_id':agent['id']})['id']
                result = subprocess.run([sys.executable,'-m','medulla_local','worker-once','--url',url,'--token-file',str(key)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=8)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertTrue(json.loads(result.stdout)['executed'])
                duplicate = subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,timeout=8)
                self.assertNotEqual(duplicate.returncode,0)
                self.assertIn('already has an active coordinator',duplicate.stderr)
            finally:
                process.terminate();process.communicate(timeout=8)
            process,url = start()
            try:
                from medulla_local.store import Store
                recovered = Store(state/'coordinator.sqlite3').snapshot()
                self.assertEqual(recovered['tasks'][0]['id'],task)
                self.assertEqual(recovered['tasks'][0]['state'],'review')
                self.assertEqual(json.loads(recovered['tasks'][0]['artifacts'][0]['content'])['instruction_words'],3)
            finally:
                process.terminate();process.communicate(timeout=8)


if __name__=='__main__':
    unittest.main()
