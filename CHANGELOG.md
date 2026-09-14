# Changelog

## 0.12.0 — September 14, 2026

First local coordinator release in Jim's fork. Independently runnable alongside existing tools, with no upstream cloud or OpenHuman dependency.

- Durable SQLite projects, explicit agent enrollment, immutable assignment payloads, dependency routing and append-only event history.
- Scoped pull-worker credentials, atomic claims, acknowledgement and START, renewable leases, attempt fencing, interruption handling and explicit retries.
- Separate execution approval and artifact acceptance. Reviews bind to a specific artifact and checksum; rejected drafts stay preserved and downstream workers receive only accepted evidence.
- Local authenticated console with assignment creation, project navigation, agent registry, history, review, credential revocation, pause/cancel and record export.
- Single-use console launch links with a 60-second lifetime, replaced in browser history before exchange; long-lived keys remain in private local files.
- Deterministic text worker and dependency/approval rehearsal. No model calls, filesystem tools, shell endpoint, provider detection, watcher changes or existing-session integration.
- Tests for concurrent claims, persistence, stale attempts/reviews, authorization, origin/host enforcement, evidence preservation, process restart and lock exclusion.

Retained upstream documentation is historical reference; `docs/fork/` describes the local implementation.
