# Local coordinator architecture

Version: 0.12.0

The coordinator runs in one Python process on macOS or Linux. It uses the standard library and SQLite. There is no cloud connection, model endpoint, repository scan or background service installation.

## Components

- `store.py`: persistent projects, agents, tasks, dependency edges, attempts, artifacts and events. Every mutation uses a fresh connection and `BEGIN IMMEDIATE`.
- `workers.py`: worker-scoped claims and attempt lifecycle. One active attempt per agent and per task is also enforced by unique database indexes.
- `server.py`: loopback HTTP API, static console, separate operator/worker authorization, request bounds and origin/host checks.
- `client.py`: loopback-only JSON client with proxies and redirects disabled.
- `local_worker.py`: deterministic text analysis through the same HTTP route available to external workers. No model or command execution.
- `security.py`: private credential files and an exclusive service lock. A second service cannot acquire the same state directory.
- `web/`: static console. It renders untrusted content as text, uses no remote resources or browser-local authorization records, and exports server-held evidence.

## Lifecycle

An assignment is immutable after creation. Dependency edges point only to existing tasks in the same project, so creating a new task cannot introduce a cycle.

`awaiting_approval → queued → claimed → delivered → running → review → completed`

Assignments without an execution gate begin queued. A claim requires all dependencies completed, the assigned worker enabled and idle, and dispatch unpaused. Claim is not delivery; the worker confirms delivery separately and then reports START. The full instruction and accepted dependency artifacts travel with the claim.

Worker completion produces an artifact, never human acceptance. The operator's acceptance names the precise artifact ID; a stale review cannot accept a later revision. Accepted artifact IDs and SHA-256 values appear in the decision event. The operator credential identifies the local operator role, not a cryptographically verified human identity.

An expired lease makes the task interrupted. There is no timer-triggered retry. The operator must establish that the old worker has stopped and document why a retry is safe. Old attempt IDs are refused after expiry, cancellation, revocation or terminal completion. Rejected output stays preserved; a retry receives the prior correction and a new attempt ID.

Pause stops new claims. Cancel withdraws one task's authorization. External workers must honor heartbeat refusals; the coordinator does not own or forcibly kill their processes. The local text worker is bounded in-process code. An OS or host failure cannot provide exactly-once external side effects; agent adapters must independently enforce idempotence or use isolated attempt workspaces.

## Persistence and recovery

State lives in the explicitly selected private directory. SQLite WAL provides atomic transitions and concurrent reads. Event triggers prevent application-level updates or deletions, but someone with filesystem access to the database can alter it; this is an audit trail, not tamper-proof storage.

A restart preserves pending tasks, reviews, approvals, completed artifacts and current leases. A still-live worker may continue within its existing lease. Expired attempts become interrupted on the next read or claim. There is no PID-based adoption and no process-name scanning. A restarted browser rereads server records.

## Deliberate exclusions

This release has no model-driven planner, native Codex/Claude/Grok/Gemini adapter, stopped-session wakeup, production deployment runner, external secrets vault or remote access. Enrolling a worker does not implement any of those. Existing sessions remain outside this coordinator until separately connected through a reviewed adapter.


## Existing project overview — 0.12.1

The separate Sources reader attaches explicitly configured local cockpit snapshots to operator state. It has no reference to worker dispatch or SQLite mutations. The console uses an Overview route for these records and retains Work for executable local assignments. See [project connections](PROJECT_CONNECTIONS.md) for the dated source contract and error behavior.
