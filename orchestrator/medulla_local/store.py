"""Transactional storage and operator operations. Worker state lives in workers.py."""

import contextlib
import hashlib
import json
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

from .schema import SCHEMA

LIVE = ('claimed', 'delivered', 'running')


class Problem(ValueError):
    """An expected domain refusal suitable for a client-facing error."""


def ident(prefix):
    return prefix + '_' + uuid.uuid4().hex[:16]


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def text(value, field, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise Problem(f'{field} must contain 1–{maximum} characters')
    return value.strip()


class Store:
    """One connection per transaction; BEGIN IMMEDIATE serializes competing claims."""

    def __init__(self, path, clock=time.time, lease_seconds=60):
        self.path = Path(path)
        self.clock = clock
        self.lease_seconds = lease_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise Problem('Database path must be a regular file, not a symlink')
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        with contextlib.closing(self.connect()) as db:
            if db.execute('PRAGMA user_version').fetchone()[0] > 1:
                raise Problem('Database belongs to a newer version; refusing to change it')
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    @contextlib.contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, db, actor, kind, task_id=None, **data):
        db.execute('INSERT INTO events(at,actor,kind,task_id,data) VALUES(?,?,?,?,?)',
                   (self.clock(), actor, kind, task_id, json.dumps(data, sort_keys=True)))

    def project(self, name, description=''):
        name = text(name, 'Project name', 100)
        if not isinstance(description, str) or len(description) > 2000:
            raise Problem('Description must be at most 2000 characters')
        pid = ident('project')
        with self.transaction() as db:
            db.execute('INSERT INTO projects VALUES(?,?,?,?)', (pid, name, description, self.clock()))
            self.event(db, 'operator', 'project.created', project_id=pid, name=name)
        return pid

    def enroll(self, name, provider):
        name, provider = text(name, 'Agent name', 80), text(provider, 'Provider', 80)
        aid, token = ident('agent'), secrets.token_urlsafe(32)
        with self.transaction() as db:
            try:
                db.execute('INSERT INTO agents(id,name,provider,token_hash,created) VALUES(?,?,?,?,?)',
                           (aid, name, provider, digest(token), self.clock()))
            except sqlite3.IntegrityError as exc:
                raise Problem('An agent with this name already exists') from exc
            self.event(db, 'operator', 'agent.enrolled', agent_id=aid, name=name)
        return aid, token

    def principal(self, token):
        with contextlib.closing(self.connect()) as db:
            row = db.execute('SELECT id FROM agents WHERE token_hash=? AND enabled=1', (digest(token),)).fetchone()
            return row['id'] if row else None

    def create_task(self, project_id, title, instruction, agent_id, dependencies=None, requires_approval=False):
        title, instruction = text(title, 'Title'), text(instruction, 'Instruction', 16000)
        if not isinstance(requires_approval, bool):
            raise Problem('requires_approval must be boolean')
        dependencies = [] if dependencies is None else dependencies
        if not isinstance(dependencies, list) or len(dependencies) > 30 or any(not isinstance(d, str) for d in dependencies):
            raise Problem('Dependencies must be a list of at most 30 task IDs')
        if len(set(dependencies)) != len(dependencies):
            raise Problem('Dependencies must be unique')
        tid = ident('task')
        payload = json.dumps([project_id, title, instruction, agent_id, sorted(dependencies), requires_approval])
        with self.transaction() as db:
            if not db.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
                raise Problem('Project not found')
            if not db.execute('SELECT 1 FROM agents WHERE id=? AND enabled=1', (agent_id,)).fetchone():
                raise Problem('Enabled agent not found')
            for dep in dependencies:
                if not db.execute('SELECT 1 FROM tasks WHERE id=? AND project_id=?', (dep, project_id)).fetchone():
                    raise Problem('Dependencies must already exist in the same project')
            state = 'awaiting_approval' if requires_approval else 'queued'
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (tid, project_id, title, instruction, agent_id, state, int(requires_approval),
                        None, digest(payload), None, self.clock(), self.clock()))
            db.executemany('INSERT INTO dependencies VALUES(?,?)', [(tid, d) for d in dependencies])
            self.event(db, 'operator', 'task.created', tid, payload_hash=digest(payload), state=state)
        return tid

    def reap(self, db):
        """Expire ownership, never silently retry an operation with unknown effects."""
        rows = db.execute("SELECT * FROM attempts WHERE state IN ('claimed','delivered','running') AND lease_until<=?", (self.clock(),)).fetchall()
        for row in rows:
            db.execute("UPDATE attempts SET state='interrupted',finished=?,failure=? WHERE id=?",
                       (self.clock(), 'Worker lease expired; outcome unknown', row['id']))
            db.execute("UPDATE tasks SET state='interrupted',updated=? WHERE id=?", (self.clock(), row['task_id']))
            self.event(db, 'coordinator', 'attempt.interrupted', row['task_id'], attempt_id=row['id'], reason='lease_expired')

    def action(self, task_id, action, note='', artifact_id=None):
        if not isinstance(note, str) or len(note) > 2000:
            raise Problem('Note must be at most 2000 characters')
        with self.transaction() as db:
            self.reap(db)
            row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if row is None:
                raise Problem('Task not found')
            state = row['state']
            if action in ('accept', 'reject'):
                artifact = db.execute('SELECT id FROM artifacts WHERE task_id=? ORDER BY rowid DESC LIMIT 1', (task_id,)).fetchone()
                if artifact is None or artifact_id != artifact['id']:
                    raise Problem('The reviewed artifact changed or was not specified; refresh before deciding')
            if action == 'approve' and state == 'awaiting_approval':
                db.execute('UPDATE tasks SET approved_at=? WHERE id=?', (self.clock(), task_id))
                target = 'queued'
            elif action == 'accept' and state == 'review':
                db.execute('UPDATE tasks SET accepted_artifact_id=? WHERE id=?', (artifact['id'], task_id))
                target = 'completed'
            elif action == 'reject' and state == 'review':
                if not note.strip():
                    raise Problem('Give the worker a reason for the revision')
                target = 'changes_requested'
            elif action == 'retry' and state in ('failed', 'interrupted', 'changes_requested'):
                if state == 'interrupted' and not note.strip():
                    raise Problem('Confirm the prior worker has stopped and describe why retry is safe')
                target = 'queued'
            elif action == 'cancel' and state not in ('completed', 'cancelled'):
                target = 'cancelled'
                db.execute("UPDATE attempts SET state='cancelled',finished=? WHERE task_id=? AND state IN ('claimed','delivered','running')", (self.clock(), task_id))
            else:
                raise Problem(f'Cannot {action} a task in {state}')
            db.execute('UPDATE tasks SET state=?,updated=? WHERE id=?', (target, self.clock(), task_id))
            details = {'note': note, 'state': target, 'payload_hash': row['payload_hash']}
            if action == 'accept':
                accepted = db.execute('SELECT id,sha256 FROM artifacts WHERE id=?', (artifact['id'],)).fetchone()
                details.update(artifact_id=accepted['id'], sha256=accepted['sha256'])
            self.event(db, 'operator', 'task.' + action, task_id, **details)
        return target

    def pause(self, paused):
        if not isinstance(paused, bool):
            raise Problem('paused must be boolean')
        with self.transaction() as db:
            db.execute("UPDATE settings SET value=? WHERE key='paused'", (json.dumps(paused),))
            self.event(db, 'operator', 'dispatch.paused' if paused else 'dispatch.resumed')

    def revoke(self, agent_id):
        with self.transaction() as db:
            if not db.execute('SELECT 1 FROM agents WHERE id=?', (agent_id,)).fetchone():
                raise Problem('Agent not found')
            db.execute('UPDATE agents SET enabled=0 WHERE id=?', (agent_id,))
            rows = db.execute("SELECT id,task_id FROM attempts WHERE agent_id=? AND state IN ('claimed','delivered','running')", (agent_id,)).fetchall()
            for row in rows:
                db.execute("UPDATE attempts SET state='interrupted',finished=?,failure='Credential revoked' WHERE id=?", (self.clock(), row['id']))
                db.execute("UPDATE tasks SET state='interrupted',updated=? WHERE id=?", (self.clock(), row['task_id']))
                self.event(db, 'operator', 'attempt.interrupted', row['task_id'], attempt_id=row['id'], reason='credential_revoked')
            self.event(db, 'operator', 'agent.revoked', agent_id=agent_id)

    def snapshot(self):
        with self.transaction() as db:
            self.reap(db)
            projects = [dict(r) for r in db.execute('SELECT * FROM projects ORDER BY created')]
            agents = [dict(r) for r in db.execute('SELECT id,name,provider,enabled,last_seen,created FROM agents ORDER BY created')]
            tasks = [dict(r) for r in db.execute('SELECT * FROM tasks ORDER BY created')]
            for task in tasks:
                task['dependencies'] = [dict(r) for r in db.execute('SELECT t.id,t.title,t.state FROM dependencies d JOIN tasks t ON d.dependency_id=t.id WHERE d.task_id=?', (task['id'],))]
                task['waiting_on'] = [d['title'] for d in task['dependencies'] if d['state'] != 'completed']
                task['attempts'] = [dict(r) for r in db.execute('SELECT * FROM attempts WHERE task_id=? ORDER BY claimed', (task['id'],))]
                task['artifacts'] = [dict(r) for r in db.execute('SELECT * FROM artifacts WHERE task_id=? ORDER BY created', (task['id'],))]
                task['history'] = [{**dict(r), 'data': json.loads(r['data'])} for r in db.execute('SELECT * FROM events WHERE task_id=? ORDER BY seq', (task['id'],))]
            return {'projects': projects, 'agents': agents, 'tasks': tasks,
                    'paused': json.loads(db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]),
                    'now': self.clock(), 'events': self.events(db=db)}

    def events(self, after=0, db=None, limit=200):
        if db is None:
            with contextlib.closing(self.connect()) as connection:
                return self.events(after, connection, limit)
        if after:
            rows = db.execute('SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?', (after, limit))
        else:
            rows = reversed(db.execute('SELECT * FROM events ORDER BY seq DESC LIMIT ?', (limit,)).fetchall())
        return [{**dict(r), 'data': json.loads(r['data'])} for r in rows]

    def export(self):
        result = self.snapshot()
        with contextlib.closing(self.connect()) as db:
            result['events'] = [{**dict(r), 'data': json.loads(r['data'])} for r in db.execute('SELECT * FROM events ORDER BY seq')]
        return result
