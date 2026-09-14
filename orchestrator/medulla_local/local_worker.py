"""A real, deterministic text worker for safe receiving-route rehearsals.

It reads only assigned text and accepted dependency artifacts through the worker
API. It has no shell, filesystem tool, external network route or model provider.
"""

import hashlib
import json
import threading
import urllib.error
from pathlib import Path

from .client import Client
from .security import private_write


def run_once(client):
    assignment = client.post('/api/worker/claim')['assignment']
    if not assignment:
        return False
    aid = assignment['attempt_id']
    def transition(operation, **data):
        return client.post('/api/worker/attempt', {'attempt_id': aid, 'operation': operation, **data})
    transition('ack')
    transition('start')
    instruction = assignment['task']['instruction']
    result = {
        'worker': 'local-text', 'model_calls': 0,
        'task_id': assignment['task']['id'], 'attempt_id': aid,
        'instruction_characters': len(instruction), 'instruction_words': len(instruction.split()),
        'instruction_sha256': hashlib.sha256(instruction.encode()).hexdigest(),
        'accepted_dependencies': [{'name': item['name'], 'expected_sha256': item['sha256'],
            'actual_sha256': hashlib.sha256(item['content'].encode()).hexdigest(),
            'matches': hashlib.sha256(item['content'].encode()).hexdigest() == item['sha256']}
            for item in assignment['dependencies']],
    }
    transition('complete', content=json.dumps(result, indent=2), name='content-fingerprint.json')
    return True


def attach(server, state_dir):
    """Start only this built-in worker; no detection or enrollment of host agents."""
    path = Path(state_dir) / 'local-worker.json'
    if path.exists():
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError('Local worker credential file must be private')
        data = json.loads(path.read_text())
        aid, token = data['agent_id'], data['token']
        if server.store.principal(token) != aid:
            raise ValueError('Local worker credential was revoked; start without --local-worker')
    else:
        aid, token = server.store.enroll('Local text worker', 'Deterministic · no model')
        private_write(path, json.dumps({'agent_id': aid, 'token': token}))
    server.local_agent_id = aid
    client = Client(server.origin, token)

    def loop():
        while not server.stopping.is_set():
            try:
                run_once(client)
            except (ValueError, urllib.error.URLError, TimeoutError):
                pass  # No invented success; an abandoned attempt expires into interrupted.
            server.stopping.wait(1)
    worker = threading.Thread(target=loop, name='medulla-local-text-worker', daemon=True)
    worker.start()
    return worker
