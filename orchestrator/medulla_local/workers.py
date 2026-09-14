"""Scoped worker lifecycle. Every mutation fences on the current attempt ID."""

import json

from .store import LIVE, Problem, digest, ident, text


class Workers:
    def __init__(self, store):
        self.store = store

    def _enabled(self, db, agent_id):
        if not db.execute('SELECT 1 FROM agents WHERE id=? AND enabled=1', (agent_id,)).fetchone():
            raise Problem('Worker credential is revoked or unknown')
        db.execute('UPDATE agents SET last_seen=? WHERE id=?', (self.store.clock(), agent_id))

    def _owned(self, db, agent_id, attempt_id):
        self._enabled(db, agent_id)
        row = db.execute('SELECT * FROM attempts WHERE id=? AND agent_id=?', (attempt_id, agent_id)).fetchone()
        if row is None or row['state'] not in LIVE or row['lease_until'] <= self.store.clock():
            raise Problem('Attempt is not active for this worker; stop this work')
        return row

    def pulse(self, agent_id):
        with self.store.transaction() as db:
            self._enabled(db, agent_id)
        return {'connected': True}

    def claim(self, agent_id):
        s = self.store
        with s.transaction() as db:
            s.reap(db)
            self._enabled(db, agent_id)
            if db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0] == 'true':
                return None
            if db.execute("SELECT 1 FROM attempts WHERE agent_id=? AND state IN ('claimed','delivered','running')", (agent_id,)).fetchone():
                return None
            row = db.execute("""SELECT t.* FROM tasks t WHERE agent_id=? AND state='queued'
                AND (requires_approval=0 OR approved_at IS NOT NULL)
                AND NOT EXISTS(SELECT 1 FROM dependencies d JOIN tasks p ON d.dependency_id=p.id
                  WHERE d.task_id=t.id AND p.state!='completed') ORDER BY created LIMIT 1""", (agent_id,)).fetchone()
            if row is None:
                return None
            aid = ident('attempt')
            db.execute('INSERT INTO attempts(id,task_id,agent_id,state,claimed,lease_until) VALUES(?,?,?,?,?,?)',
                       (aid, row['id'], agent_id, 'claimed', s.clock(), s.clock() + s.lease_seconds))
            db.execute("UPDATE tasks SET state='claimed',updated=? WHERE id=?", (s.clock(), row['id']))
            s.event(db, agent_id, 'attempt.claimed', row['id'], attempt_id=aid)
            deps = [dict(r) for r in db.execute("""SELECT a.name,a.content,a.sha256 FROM dependencies d
                JOIN tasks t ON t.id=d.dependency_id JOIN artifacts a ON a.id=t.accepted_artifact_id
                WHERE d.task_id=?""", (row['id'],))]
            feedback = [json.loads(r['data']) for r in db.execute("SELECT data FROM events WHERE task_id=? AND kind='task.reject' ORDER BY seq DESC LIMIT 1", (row['id'],))]
            return {'attempt_id': aid, 'task': {**dict(row), 'state': 'claimed'}, 'dependencies': deps,
                    'feedback': feedback, 'lease_seconds': s.lease_seconds}

    def transition(self, agent_id, attempt_id, operation, content='', name='result.txt', reason=''):
        s = self.store
        if operation == 'complete':
            text(content, 'Artifact', 64000)  # Validate without altering the evidence bytes.
            name = text(name, 'Artifact name', 120)
            if '/' in name or '\\' in name or name in ('.', '..'):
                raise Problem('Artifact name must be a filename, not a path')
        if operation == 'fail':
            reason = text(reason, 'Failure reason', 2000)
        with s.transaction() as db:
            row = self._owned(db, agent_id, attempt_id)
            state = row['state']
            if operation == 'heartbeat':
                db.execute('UPDATE attempts SET lease_until=? WHERE id=?', (s.clock() + s.lease_seconds, attempt_id))
                return {'state': state, 'lease_seconds': s.lease_seconds}
            if operation == 'ack' and state == 'claimed':
                target = 'delivered'
                db.execute('UPDATE attempts SET acknowledged=? WHERE id=?', (s.clock(), attempt_id))
            elif operation == 'start' and state == 'delivered':
                target = 'running'
                db.execute('UPDATE attempts SET started=? WHERE id=?', (s.clock(), attempt_id))
            elif operation == 'complete' and state == 'running':
                target = 'review'
                db.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)',
                           (ident('artifact'), row['task_id'], attempt_id, name, content, digest(content), s.clock()))
                db.execute('UPDATE attempts SET finished=? WHERE id=?', (s.clock(), attempt_id))
            elif operation == 'fail' and state in LIVE:
                target = 'failed'
                db.execute('UPDATE attempts SET finished=?,failure=? WHERE id=?', (s.clock(), reason, attempt_id))
            else:
                raise Problem(f'Cannot {operation} an attempt in {state}')
            db.execute('UPDATE attempts SET state=?,lease_until=? WHERE id=?', (target, s.clock() + s.lease_seconds, attempt_id))
            db.execute('UPDATE tasks SET state=?,updated=? WHERE id=?', (target, s.clock(), row['task_id']))
            details = {'attempt_id': attempt_id, 'state': target}
            if operation == 'complete':
                details['sha256'] = digest(content)
            if reason:
                details['reason'] = reason
            s.event(db, agent_id, 'attempt.' + operation, row['task_id'], **details)
            return {'state': target, 'lease_seconds': s.lease_seconds}
