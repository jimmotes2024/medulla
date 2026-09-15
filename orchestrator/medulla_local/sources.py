"""Explicit, read-only cockpit connections. Never dispatch or execute source content."""

import hashlib
import json
import os
import re
import stat
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

LIMIT = 8 * 1024 * 1024
TASK_FILE = 'tasks/TASKS.v1.json'
CHECKPOINT_FILE = 'checkpoints/gates.v1.json'


def read_json(root, relative, limit=LIMIT):
    """Open fixed relative paths without following files or directory symlinks."""
    parts = Path(relative).parts
    if not parts or any(p in ('..', '/') for p in parts):
        raise ValueError('Invalid source path')
    flags = os.O_RDONLY | os.O_NOFOLLOW
    fd = os.open(root, flags | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
        source = os.open(parts[-1], flags | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(source, 'rb') as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise ValueError('Source must be a bounded regular JSON file')
            raw = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        if len(raw) > limit or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Source changed during read; refresh again')
        return json.loads(raw), hashlib.sha256(raw).hexdigest()
    finally:
        os.close(fd)


def stamp(value):
    if not isinstance(value, str):
        raise ValueError('Source timestamp is missing')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Source timestamp requires a timezone')
    return parsed.timestamp()


def words(value, maximum=16000):
    return value[:maximum] if isinstance(value, str) else ''


def inspect(entry):
    root = Path(entry['directory'])
    tasks, task_hash = read_json(root, TASK_FILE)
    gates, checkpoint_hash = read_json(root, CHECKPOINT_FILE)
    if tasks.get('schema') != 'tasks.v1' or not isinstance(tasks.get('tasks'), list):
        raise ValueError('Unsupported task source schema')
    if gates.get('schema') != 'kredo-panel-gate-disposition.v1':
        raise ValueError('Unsupported checkpoint schema')
    if len(tasks['tasks']) > 2000:
        raise ValueError('Task source exceeds 2000 records')
    task_at = stamp(tasks.get('generated_at'))
    candidates = []
    for key, item in gates.get('judge_diagnostics', {}).items():
        if key.startswith('owned_') and isinstance(item, dict) and item.get('as_of_cutoff_utc'):
            candidates.append((stamp(item['as_of_cutoff_utc']), key, item))
    if not candidates:
        raise ValueError('No dated project checkpoint is available')
    checkpoint_at, checkpoint_key, checkpoint = max(candidates, key=lambda x: (x[0], x[1]))
    records = []
    seen = set()
    for task in tasks['tasks']:
        if not isinstance(task, dict) or not isinstance(task.get('id'), str) or task['id'] in seen:
            raise ValueError('Task identities must be unique strings')
        seen.add(task['id'])
        if not isinstance(task.get('status'), str):
            raise ValueError('Task status is missing')
        record = {k: words(task.get(k)) for k in ('id', 'title', 'owner', 'status', 'blocker', 'next_action', 'evidence_required', 'updated_at')}
        record['updated'] = stamp(task.get('updated_at'))
        records.append(record)
    items = []
    for item in checkpoint.get('items', []):
        if isinstance(item, dict):
            items.append({k: words(item.get(k)) for k in ('key', 'lamp', 'state', 'word', 'cls')})
    decision = checkpoint.get('decision', {})
    if not isinstance(decision, dict):
        decision = {}
    return {
        'id': entry['id'], 'name': entry['name'], 'status': 'available', 'read_only': True,
        'directory': str(root), 'cockpit_path': str(root / 'panel/cockpit/index.html'),
        'checkpoint_at': checkpoint_at, 'tasks_at': task_at, 'tasks_older': task_at < checkpoint_at,
        'checkpoint_key': checkpoint_key,
        'focus': words(checkpoint.get('vocabulary')), 'sample': words(checkpoint.get('sample')),
        'scope': words(checkpoint.get('qualification')), 'next': words(checkpoint.get('next')),
        'decision': {k: words(decision.get(k)) for k in ('owner', 'recommended', 'alternative')},
        'items': items, 'tasks': sorted(records, key=lambda t: t['updated'], reverse=True),
        'counts': dict(Counter(t['status'] for t in records)),
        'sources': [{'path': TASK_FILE, 'sha256': task_hash}, {'path': CHECKPOINT_FILE, 'sha256': checkpoint_hash}],
    }


class Sources:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = threading.Lock()
        self.cached, self.read_at = None, 0

    def entries(self):
        try:
            data, _ = read_json(self.directory, 'sources.json', 65536)
        except FileNotFoundError:
            if not (self.directory / 'sources.json').is_symlink():
                return []
            raise ValueError('Source configuration cannot be a symlink')
        if not isinstance(data, list) or len(data) > 20:
            raise ValueError('Expected at most 20 source connections')
        ids = set()
        for entry in data:
            if (not isinstance(entry, dict) or not re.fullmatch(r'source_[a-f0-9]{16}', entry.get('id', ''))
                    or entry['id'] in ids or not isinstance(entry.get('name'), str) or not entry['name'].strip()
                    or len(entry['name']) > 100 or not isinstance(entry.get('directory'), str)
                    or not Path(entry['directory']).is_absolute()):
                raise ValueError('Invalid source connection')
            ids.add(entry['id'])
        return data

    def snapshot(self):
        with self.lock:
            if self.cached is not None and time.monotonic() - self.read_at < 5:
                return self.cached
            result = {'projects': [], 'error': None, 'checked_at': time.time()}
            try:
                entries = self.entries()
            except (ValueError, OSError, TypeError):
                entries = []
                result['error'] = 'Project connections could not be read. Check the local source configuration.'
            for entry in entries:
                try:
                    result['projects'].append(inspect(entry))
                except (ValueError, OSError, TypeError, AttributeError, KeyError, RecursionError):
                    result['projects'].append({'id': entry['id'], 'name': entry['name'], 'status': 'unavailable',
                                               'read_only': True, 'error': 'The project source is missing, changing, or incompatible. No cached status is being presented as current.'})
            self.cached, self.read_at = result, time.monotonic()
            return result

    def connect(self, directory, name):
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError('Project name must contain 1–100 characters')
        root = Path(directory).resolve(strict=True)
        ident = 'source_' + hashlib.sha256(str(root).encode()).hexdigest()[:16]
        entry = {'id': ident, 'name': name.strip(), 'directory': str(root)}
        inspect(entry)  # Validate before recording anything; source files remain read-only.
        with self.lock:
            entries = [e for e in self.entries() if e['id'] != ident]
            if len(entries) >= 20:
                raise ValueError('At most 20 source connections are supported')
            entries.append(entry)
            fd, temp = tempfile.mkstemp(prefix='.sources-', dir=self.directory)
            try:
                with os.fdopen(fd, 'w') as handle:
                    json.dump(entries, handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, self.directory / 'sources.json')
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            self.cached = None
        return ident
