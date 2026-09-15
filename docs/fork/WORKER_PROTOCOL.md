# Worker protocol

Version: 0.12.0 (local API 1)

Workers connect explicitly to the URL printed by the coordinator. Enroll through the operator console or CLI, then give only that worker its token. No ambient agent identity, CLI credentials or host configuration is read.

All operations are JSON POSTs with `Authorization: Bearer WORKER_KEY`. Do not put keys in prompts, URLs, shell command arguments or logs. The included client takes a private token file; the CLI reads JSON from stdin.

| Endpoint | Request | Result |
| --- | --- | --- |
| `/api/worker/claim` | `{}` | `assignment: null` or a task, accepted dependency artifacts, feedback, attempt ID and lease duration |
| `/api/worker/pulse` | `{}` | Idle presence receipt |
| `/api/worker/attempt` | attempt_id, operation=`ack` | Confirms actual delivery |
| Same | operation=`start` | START, permitted only after ack |
| Same | operation=`heartbeat` | Extends a live lease |
| Same | operation=`complete`, name, content | Saves an artifact and enters review |
| Same | operation=`fail`, reason | Ends the attempt with a failure record |

Default lease: 60 seconds. Send heartbeats more often than the lease duration (20 seconds is appropriate). A refusal, timeout with unresolved ownership, or credential loss means stop further effects until ownership is re-established. Never silently claim a second copy. There is at most one active attempt per worker.

Keep cancellation responsive between tool calls; long-running tools need an interruptible adapter. The coordinator's local text worker is not a general model adapter and must not be presented as one.

Artifacts are UTF-8 text of at most 64,000 characters. The service preserves the exact submitted string and computes SHA-256. The filename is a label, not a filesystem path. Completion does not imply acceptance. A reviewed revision's artifact ID is explicitly pinned for downstream work.

Example enrollment (from `orchestrator/`, using paths chosen for this evaluation):

```bash
python3 -m medulla_local enroll --url http://127.0.0.1:PORT \
  --admin-key-file .medulla-local/operator.key \
  --name 'Isolated worker' --provider 'Custom pull adapter' --out worker.key
```

The CLI prints the agent ID and credential path, never the token. Use `python3 -m medulla_local call --url ... --token-file worker.key /api/worker/claim` with `{}` on stdin to receive one assignment. Building a harness-specific adapter is separate work; do not launch or alter an existing interactive agent merely to satisfy this example.

`worker-once` is an executable example adapter. It calculates a content fingerprint and validates accepted dependency hashes through the real HTTP lifecycle, with no model or shell tool.
