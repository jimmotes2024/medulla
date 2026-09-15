"""Read-only integrations use disposable files, never actual user projects."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from medulla_local.sources import Sources, read_json


def write_cockpit(root):
    (root/'tasks').mkdir(parents=True)
    (root/'checkpoints').mkdir()
    tasks = {'schema': 'tasks.v1', 'generated_at': '2026-09-14T12:00:00Z', 'tasks': [
        {'id': 'EXAMPLE-1', 'title': 'Old recorded work', 'owner': 'Example reviewer', 'status': 'in_progress',
         'updated_at': '2026-09-14T11:00:00Z', 'next_action': 'An older instruction'}]}
    gates = {'schema': 'kredo-panel-gate-disposition.v1', 'judge_diagnostics': {
        'owned_earlier': {'as_of_cutoff_utc': '2026-09-13T12:00:00Z', 'vocabulary': 'Earlier focus'},
        'owned_latest': {'as_of_cutoff_utc': '2026-09-15T12:00:00Z', 'vocabulary': 'Latest focus',
                         'next': 'Review the recorded decision', 'items': [{'key': 'update', 'lamp': 'Recorded blocker', 'word': 'Example evidence'}]}}}
    (root/'tasks/TASKS.v1.json').write_text(json.dumps(tasks))
    (root/'checkpoints/gates.v1.json').write_text(json.dumps(gates))
    return tasks, gates


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)/'project'
        self.state = Path(self.temp.name)/'state'; self.state.mkdir()
        self.tasks, self.gates = write_cockpit(self.root)
        self.sources = Sources(self.state)

    def tearDown(self):
        self.temp.cleanup()

    def connect(self):
        self.sources.connect(self.root, 'Example project')
        return self.sources.snapshot()['projects'][0]

    def test_newest_checkpoint_and_older_tasks_remain_distinct_without_source_writes(self):
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*.json')}
        project = self.connect()
        self.assertEqual(project['focus'], 'Latest focus')
        self.assertTrue(project['tasks_older'])
        self.assertEqual(project['tasks'][0]['next_action'], 'An older instruction')
        self.assertTrue(project['read_only'])
        for p, (content, modified) in before.items():
            self.assertEqual(p.read_bytes(), content)
            self.assertEqual(p.stat().st_mtime_ns, modified)
        self.assertEqual(project['sources'][0]['sha256'], hashlib.sha256((self.root/'tasks/TASKS.v1.json').read_bytes()).hexdigest())

    def test_persistent_connection_is_deduplicated_and_private(self):
        first = self.sources.connect(self.root, 'First name')
        self.assertEqual(first, self.sources.connect(self.root, 'New name'))
        self.assertEqual((self.state/'sources.json').stat().st_mode & 0o777, 0o600)
        restarted = Sources(self.state).snapshot()
        self.assertEqual(len(restarted['projects']), 1)
        self.assertEqual(restarted['projects'][0]['name'], 'New name')

    def test_missing_source_is_explicit_and_does_not_retain_old_status(self):
        self.connect()
        (self.root/'tasks/TASKS.v1.json').unlink()
        self.sources.read_at = 0
        project = self.sources.snapshot()['projects'][0]
        self.assertEqual(project['status'], 'unavailable')
        self.assertNotIn('tasks', project)
        self.assertNotIn('focus', project)

    def test_changed_source_refreshes_after_cache_expiry(self):
        self.connect()
        self.gates['judge_diagnostics']['owned_latest']['vocabulary'] = 'Changed focus'
        (self.root/'checkpoints/gates.v1.json').write_text(json.dumps(self.gates))
        self.sources.read_at = 0
        self.assertEqual(self.sources.snapshot()['projects'][0]['focus'], 'Changed focus')

    def test_file_and_directory_symlinks_are_refused(self):
        target = self.root/'tasks/TASKS.v1.json'
        original = self.root/'saved.json'; target.rename(original); target.symlink_to(original)
        with self.assertRaises(OSError):
            self.connect()
        target.unlink(); original.rename(target)
        (self.root/'tasks').rename(self.root/'saved-tasks')
        (self.root/'tasks').symlink_to(self.root/'saved-tasks', target_is_directory=True)
        with self.assertRaises(OSError):
            self.connect()

    def test_malformed_or_incompatible_sources_do_not_break_other_state(self):
        self.connect()
        for bad in ('{broken', '[]', '{"schema":"future"}'):
            (self.root/'tasks/TASKS.v1.json').write_text(bad)
            self.sources.read_at = 0
            self.assertEqual(self.sources.snapshot()['projects'][0]['status'], 'unavailable')
        (self.state/'sources.json').write_text('{broken')
        self.sources.read_at = 0
        self.assertIsNotNone(self.sources.snapshot()['error'])

    def test_missing_timestamp_duplicate_ids_and_oversize_are_rejected(self):
        self.tasks['tasks'].append(dict(self.tasks['tasks'][0]))
        (self.root/'tasks/TASKS.v1.json').write_text(json.dumps(self.tasks))
        with self.assertRaises(ValueError):
            self.connect()
        self.tasks['tasks'].pop(); self.tasks['generated_at'] = '2026-09-14T12:00:00'
        (self.root/'tasks/TASKS.v1.json').write_text(json.dumps(self.tasks))
        with self.assertRaises(ValueError):
            self.connect()
        with self.assertRaises(ValueError):
            read_json(self.root, 'tasks/TASKS.v1.json', 10)

    def test_untrusted_project_text_is_returned_as_data_without_execution(self):
        payload = '<script>alert("example")</script>'
        self.tasks['tasks'][0]['title'] = payload
        (self.root/'tasks/TASKS.v1.json').write_text(json.dumps(self.tasks))
        self.assertEqual(self.connect()['tasks'][0]['title'], payload)


if __name__ == '__main__':
    unittest.main()
