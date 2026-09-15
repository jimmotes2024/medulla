"""SQLite schema; events are append-only within the application database."""

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO settings VALUES('paused','false');
CREATE TABLE IF NOT EXISTS projects(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS agents(
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, provider TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL DEFAULT 1,
 last_seen REAL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 title TEXT NOT NULL, instruction TEXT NOT NULL, agent_id TEXT NOT NULL REFERENCES agents(id),
 state TEXT NOT NULL, requires_approval INTEGER NOT NULL,
 approved_at REAL, payload_hash TEXT NOT NULL, accepted_artifact_id TEXT,
 created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS dependencies(
 task_id TEXT NOT NULL REFERENCES tasks(id), dependency_id TEXT NOT NULL REFERENCES tasks(id),
 PRIMARY KEY(task_id,dependency_id), CHECK(task_id != dependency_id));
CREATE TABLE IF NOT EXISTS attempts(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
 agent_id TEXT NOT NULL REFERENCES agents(id), state TEXT NOT NULL,
 claimed REAL NOT NULL, acknowledged REAL, started REAL, lease_until REAL NOT NULL,
 finished REAL, failure TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_attempt_per_task ON attempts(task_id)
 WHERE state IN ('claimed','delivered','running');
CREATE UNIQUE INDEX IF NOT EXISTS one_live_attempt_per_agent ON attempts(agent_id)
 WHERE state IN ('claimed','delivered','running');
CREATE TABLE IF NOT EXISTS artifacts(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
 attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id), name TEXT NOT NULL,
 content TEXT NOT NULL, sha256 TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, actor TEXT NOT NULL,
 kind TEXT NOT NULL, task_id TEXT, data TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_event_update BEFORE UPDATE ON events
 BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_event_delete BEFORE DELETE ON events
 BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
PRAGMA user_version=1;
"""
