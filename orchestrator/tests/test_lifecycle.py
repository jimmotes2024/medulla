"""Race, restart, evidence and authorization tests against the real SQLite store."""

import concurrent.futures
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from medulla_local.store import Store, Problem
from medulla_local.workers import Workers


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1000.0
        self.path = Path(self.tmp.name) / 'db'
        self.store = Store(self.path, lambda: self.now, lease_seconds=30)
        self.workers = Workers(self.store)
        self.project = self.store.project('Test project')
        self.agent, self.token = self.store.enroll('One', 'test')
        self.other, self.other_token = self.store.enroll('Two', 'test')

    def tearDown(self):
        self.tmp.cleanup()

    def task(self, **kw):
        return self.store.create_task(self.project, 'Task', 'Do bounded work', self.agent, **kw)

    def row(self, tid):
        return next(t for t in self.store.snapshot()['tasks'] if t['id'] == tid)

    def finish(self, tid, content='evidence'):
        assignment = self.workers.claim(self.agent)
        self.assertEqual(assignment['task']['id'], tid)
        aid = assignment['attempt_id']
        self.workers.transition(self.agent, aid, 'ack')
        self.workers.transition(self.agent, aid, 'start')
        self.workers.transition(self.agent, aid, 'complete', content=content)
        return self.row(tid)['artifacts'][-1]['id']

    def test_dependency_waits_for_exact_human_acceptance(self):
        first = self.task()
        second = self.task(dependencies=[first])
        artifact = self.finish(first)
        self.assertIsNone(self.workers.claim(self.agent))
        self.store.action(first, 'accept', artifact_id=artifact)
        next_job = self.workers.claim(self.agent)
        self.assertEqual(next_job['task']['id'], second)
        self.assertEqual(next_job['dependencies'][0]['content'], 'evidence')

    def test_approval_is_required_before_any_claim(self):
        tid = self.task(requires_approval=True)
        self.assertIsNone(self.workers.claim(self.agent))
        self.store.action(tid, 'approve')
        self.assertIsNotNone(self.workers.claim(self.agent))

    def test_completion_requires_delivery_then_start(self):
        self.task()
        aid = self.workers.claim(self.agent)['attempt_id']
        for op in ('start', 'complete'):
            with self.assertRaises(Problem):
                self.workers.transition(self.agent, aid, op, content='early')
        self.workers.transition(self.agent, aid, 'ack')
        with self.assertRaises(Problem):
            self.workers.transition(self.agent, aid, 'complete', content='early')

    def test_other_agent_cannot_operate_attempt(self):
        self.task()
        aid = self.workers.claim(self.agent)['attempt_id']
        for op in ('ack', 'start', 'heartbeat', 'complete', 'fail'):
            with self.assertRaises(Problem):
                self.workers.transition(self.other, aid, op, content='spoofed', reason='spoofed')

    def test_many_simultaneous_claims_admit_one(self):
        tid = self.task()
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: self.workers.claim(self.agent), range(12)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(self.row(tid)['attempts']), 1)

    def test_worker_has_one_active_assignment(self):
        self.task(); self.task()
        self.assertIsNotNone(self.workers.claim(self.agent))
        self.assertIsNone(self.workers.claim(self.agent))

    def test_restart_retains_live_ownership_without_duplicate(self):
        tid = self.task()
        aid = self.workers.claim(self.agent)['attempt_id']
        self.workers.transition(self.agent, aid, 'ack')
        self.workers.transition(self.agent, aid, 'start')
        restarted = Store(self.path, lambda: self.now)
        self.assertIsNone(Workers(restarted).claim(self.agent))
        Workers(restarted).transition(self.agent, aid, 'complete', content='survived')
        self.assertEqual(self.row(tid)['state'], 'review')

    def test_expiry_does_not_retry_and_fences_old_worker(self):
        tid = self.task()
        old = self.workers.claim(self.agent)['attempt_id']
        self.now += 31
        self.assertIsNone(self.workers.claim(self.agent))
        self.assertEqual(self.row(tid)['state'], 'interrupted')
        with self.assertRaises(Problem):
            self.store.action(tid, 'retry')
        self.store.action(tid, 'retry', note='Prior disposable worker stopped; no external effects')
        new = self.workers.claim(self.agent)['attempt_id']
        self.assertNotEqual(old, new)
        with self.assertRaises(Problem):
            self.workers.transition(self.agent, old, 'heartbeat')
        with self.assertRaises(Problem):
            self.workers.transition(self.agent, old, 'complete', content='stale')

    def test_live_heartbeat_extends_ownership(self):
        tid = self.task()
        aid = self.workers.claim(self.agent)['attempt_id']
        self.now += 20
        self.workers.transition(self.agent, aid, 'heartbeat')
        self.now += 20
        self.assertEqual(self.row(tid)['state'], 'claimed')

    def test_pause_survives_restart_and_does_not_stop_inflight(self):
        tid = self.task()
        aid = self.workers.claim(self.agent)['attempt_id']
        self.store.pause(True)
        self.workers.transition(self.agent, aid, 'ack')
        self.workers.transition(self.agent, aid, 'start')
        self.workers.transition(self.agent, aid, 'complete', content='completed during pause')
        self.task()
        restarted = Store(self.path, lambda: self.now)
        self.assertTrue(restarted.snapshot()['paused'])
        self.assertIsNone(Workers(restarted).claim(self.agent))

    def test_cancel_withdraws_only_selected_attempt(self):
        tid = self.task()
        other_task = self.store.create_task(self.project, 'Other', 'Other work', self.other)
        a = self.workers.claim(self.agent)['attempt_id']
        b = self.workers.claim(self.other)['attempt_id']
        self.store.action(tid, 'cancel')
        with self.assertRaises(Problem):
            self.workers.transition(self.agent, a, 'ack')
        self.workers.transition(self.other, b, 'ack')
        self.assertEqual(self.row(other_task)['state'], 'delivered')

    def test_revocation_invalidates_auth_and_active_work(self):
        tid = self.task()
        aid = self.workers.claim(self.agent)['attempt_id']
        self.store.revoke(self.agent)
        self.assertIsNone(self.store.principal(self.token))
        with self.assertRaises(Problem):
            self.workers.transition(self.agent, aid, 'ack')
        self.assertEqual(self.row(tid)['state'], 'interrupted')

    def test_stale_review_cannot_accept_new_artifact(self):
        tid = self.task()
        first = self.finish(tid, 'first draft')
        self.store.action(tid, 'reject', note='Correct the calculation', artifact_id=first)
        self.store.action(tid, 'retry')
        second = self.finish(tid, 'corrected draft')
        with self.assertRaises(Problem):
            self.store.action(tid, 'accept', artifact_id=first)
        self.store.action(tid, 'accept', artifact_id=second)
        self.assertEqual(self.row(tid)['accepted_artifact_id'], second)

    def test_downstream_receives_only_accepted_revision_even_same_timestamp(self):
        tid = self.task()
        first = self.finish(tid, 'rejected draft')
        self.store.action(tid, 'reject', note='Revise', artifact_id=first)
        self.store.action(tid, 'retry')
        second = self.finish(tid, 'accepted draft')
        self.store.action(tid, 'accept', artifact_id=second)
        self.task(dependencies=[tid])
        artifacts = self.workers.claim(self.agent)['dependencies']
        self.assertEqual([a['content'] for a in artifacts], ['accepted draft'])

    def test_evidence_bytes_and_hash_are_preserved(self):
        tid = self.task()
        content = '  evidence\n\n'
        self.finish(tid, content)
        artifact = self.row(tid)['artifacts'][0]
        self.assertEqual(artifact['content'], content)
        self.assertEqual(artifact['sha256'], hashlib.sha256(content.encode()).hexdigest())

    def test_event_table_rejects_mutation(self):
        with self.store.transaction() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM events')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE events SET actor='spoofed'")

    def test_exports_omit_credentials_and_include_receipts(self):
        tid = self.task(); artifact = self.finish(tid)
        self.store.action(tid, 'accept', artifact_id=artifact)
        result = self.store.export()
        import json
        serialized = json.dumps(result)
        self.assertNotIn(self.token, serialized)
        self.assertNotIn('token_hash', serialized)
        accepted = [e for e in result['events'] if e['kind'] == 'task.accept'][0]
        self.assertEqual(accepted['data']['artifact_id'], artifact)
        self.assertEqual(accepted['data']['sha256'], hashlib.sha256(b'evidence').hexdigest())

    def test_rejects_invalid_cross_project_and_future_dependencies(self):
        tid = self.task()
        project = self.store.project('Different')
        with self.assertRaises(Problem):
            self.store.create_task(project, 'Bad', 'Bad', self.agent, [tid])
        with self.assertRaises(Problem):
            self.task(dependencies=['unknown'])
        with self.assertRaises(Problem):
            self.task(dependencies=[tid, tid])
        with self.assertRaises(Problem):
            self.task(requires_approval='false')

    def test_failed_dependency_stays_blocked(self):
        first = self.task(); self.task(dependencies=[first])
        aid = self.workers.claim(self.agent)['attempt_id']
        self.workers.transition(self.agent, aid, 'fail', reason='Unable to complete')
        self.assertIsNone(self.workers.claim(self.agent))

    def test_terminal_task_cannot_be_silently_reopened(self):
        tid = self.task(); artifact = self.finish(tid)
        self.store.action(tid, 'accept', artifact_id=artifact)
        for op in ('retry', 'cancel', 'approve'):
            with self.assertRaises(Problem):
                self.store.action(tid, op)

    def test_newer_database_and_symlink_are_refused(self):
        with self.store.transaction() as db:
            db.execute('PRAGMA user_version=99')
        with self.assertRaises(Problem):
            Store(self.path)
        link = Path(self.tmp.name)/'link';link.symlink_to(self.path)
        with self.assertRaises(Problem):
            Store(link)


if __name__ == '__main__':
    unittest.main()
