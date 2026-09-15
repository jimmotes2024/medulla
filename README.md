# Medulla Local

**Version 0.12.1 · Jim's orchestration fork**

A local workspace for agent assignments, ownership, handoffs and reviewed results. Built alongside existing agents without taking over their sessions.

The coordinator stores real work in SQLite, exposes a scoped pull-worker API, and serves a human console on loopback. It has no cloud, model or third-party runtime dependency. Python 3.11+ on macOS or Linux is sufficient.

## Run

From this repository:

```bash
cd orchestrator
python3 -m medulla_local serve --local-worker
```

The service chooses a free loopback port and prints its URL and private operator-key file path. In a second terminal, from the same directory:

```bash
python3 -m medulla_local open-url
```

Open the single-use link within 60 seconds. The browser exchanges it for an HttpOnly session and removes the code from its address. Alternatively open the bare URL and paste the operator key into the sign-in form. Do not share connection links or keys.

State defaults to `orchestrator/.medulla-local/` and is ignored by Git. Use `--state-dir` to choose an isolated private directory. No startup agent, scheduled task or background OS service is installed. Stop with Ctrl-C; restart with the same state directory to retain records.

## First use

The workspace opens on **Overview**. Connected existing projects show their dated checkpoint, owners, next step and recorded tasks. Connections are read-only; they do not enroll agents or dispatch imported tasks. Select **Work** for this coordinator's own assignments and rehearsal.

In **Work**, select **Run isolated rehearsal** when the assignment list is empty. The built-in local text worker receives the assignment through HTTP, acknowledges it, reports START and submits a real content fingerprint. Accept its result, approve the second assignment and inspect the downstream receipt. This exercise makes zero model calls and touches no external agent or project.

Create projects and assignments, choose an enrolled worker, set reviewed dependencies, and optionally require an execution approval. A worker result always returns for operator acceptance. Changes requested, interrupted attempts, cancellations, disconnected workers and dependency waits remain distinct.

The local text worker computes fingerprints and word counts; it is explicitly not an AI agent. Omit `--local-worker` for a coordinator with only explicitly enrolled external workers. Enrollment creates a credential but never launches, resumes or migrates a session.

## Current capabilities

- Durable project queue and dependency-aware dispatch.
- Per-worker credentials, atomic claims, delivery/START receipts and heartbeats.
- Attempt fencing, explicit recovery, pause and cooperative cancellation.
- Artifact checksums, revision history, exact-artifact acceptance and approval gates.
- Local console, worker registry, timestamped history and credential-free record export.
- Real disposable-process and restart tests.

Native harness adapters and model-driven planning are not connected in this release. Existing agent work remains outside this coordinator. See the [architecture](docs/fork/ARCHITECTURE.md), [worker protocol](docs/fork/WORKER_PROTOCOL.md), [security boundaries](docs/fork/SECURITY.md) and [release plan](docs/fork/PLAN.md).

## Connect an existing cockpit

To connect an existing cockpit, run this from `orchestrator/` after starting the coordinator:

```bash
python3 -m medulla_local connect-cockpit \
  --directory /path/to/existing/instrument_panel --name "Example project"
```

This reads only `tasks/TASKS.v1.json` and `checkpoints/gates.v1.json` using the supported cockpit schemas. The connection is saved in the ignored private state directory. The running service checks for changes while the console is open, with a five-second read cache. Older task instructions are reference material, never automatically executed or silently promoted to current directions. Missing or incompatible files produce an unavailable state. See [read-only project connections](docs/fork/PROJECT_CONNECTIONS.md).

## Verify

```bash
cd orchestrator
python3 -m unittest discover -s tests -v
node --check medulla_local/web/app.js
```

Tests use temporary state, loopback servers and disposable deterministic workers. They do not call a model or use existing agent sessions.

## Upstream

This fork preserves the upstream documentation/distribution history. The local coordinator is new code informed by the retained Medulla client architecture; it does not claim to run the upstream Rust SDK or hosted orchestrator. Exact [source provenance](docs/fork/UPSTREAM.md) and [changes](CHANGELOG.md) are recorded.

The original upstream product documentation in `gitbooks/` and older files under `docs/` describes upstream behavior. Its installers install that upstream product, not this local coordinator; use the Run commands above.

Local code license: GPL-3.0-only, consistent with the retained client's declaration. See [GNU GPL version 3](https://www.gnu.org/licenses/gpl-3.0.html).
