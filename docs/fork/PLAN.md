# Local orchestration release plan

Version: 0.12.0-dev.1

Build an independently runnable local coordinator and human console in this fork. Preserve the upstream documentation and source provenance. No current agent work is enrolled or modified during development.

## First release completion criteria

1. Persistent projects, agent registry, dependency-aware assignments and append-only events.
2. Scoped pull-worker protocol with atomic claims, delivery acknowledgement, START, heartbeat, attempt fencing, artifacts and separate human acceptance.
3. Explicit approval before gated work; reviewed dependencies before downstream work starts. Pausing, cancellation and interrupted-work handling survive restart.
4. Local authenticated console for real data, task creation, review, approvals and inspectable event history. Export includes actions and evidence hashes, never credentials.
5. Real disposable worker rehearsal of the receiving route, task execution and evidence submission; no live model calls or named-session integration.
6. Tests cover competing claims, expired attempts, ownership, invalid state transitions, persistence, approval bypass, cross-origin requests and worker/operator boundaries.
7. Versioned documentation and passing verification committed and pushed to this fork's development branch.

## Adoption boundary

This release coordinates explicitly connected workers. It does not wake, migrate, message, read or take over existing Axiom, Vanguard, Dara, Gemini or other sessions. Their enrollment is a later, deliberate cutover. Model-driven planning and native harness adapters are subsequent increments, not claims of this release.

## Architecture decision

The retained Medulla 0.11.0 source is tied to an uninitialized OpenHuman dependency. The existing Bridge serves mainly mock state. Use Medulla's separation of UI/runtime, typed run identity and lifecycle ideas, but implement the small local durability/authorization boundary independently with SQLite and the Python standard library. This is explicit new fork code, not a claim that the retained Rust engine is already connected.
