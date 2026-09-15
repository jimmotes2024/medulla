# Verification — 0.12.0

September 14, 2026

## Executed checks

- `python3 -m unittest discover -s tests -v`: 38 passed.
- `node --check medulla_local/web/app.js`: passed.
- Python compile check and Git whitespace check: passed.
- Static console element references: all referenced IDs exist; no external resources in the HTML.
- Actual service console HTTP response: 200.
- Actual local worker rehearsal: first assignment claimed, acknowledged, started and submitted an artifact through HTTP; first task remains in review and the dependent task remains awaiting approval. No fabricated human acceptance.

The process test starts a disposable coordinator, enrolls a disposable worker, executes that worker as a separate Python process, verifies its computed output, refuses a competing service for the same state, restarts the service and verifies the retained task/artifact. All processes and files in that test are temporary and cleaned up.

## Covered failure cases

Concurrent claims, live ownership across restart, expiry without automatic retries, stale attempts, stale artifact review, cancellation limited to one assignment, revocation, approval gates, rejected evidence preservation, downstream accepted-artifact binding, immutable event operations, same-timestamp revisions, future database versions, symlink refusal, host/origin controls, worker/operator separation, malformed/oversized requests, secret/path serving, cookie invalidation, and single-use/expired launch tickets.

## Limits

Native Codex/Claude/Grok/Gemini integration and live model calls were not run. The retained upstream Rust code and its dependency tree were not built. This release does not claim full-system agent adoption or production execution readiness. Console syntax, element bindings and HTTP behavior were checked; no browser interaction/visual test suite was run. A local preview was requested through the app, which reported it queued.

An unprivileged test invocation could not bind loopback sockets in the tool sandbox. The suite was rerun with the approved local-socket permission and passed; the initial environment refusal was not a product failure.


## 0.12.1 — September 15, 2026

49 tests passed, adding eleven source and HTTP checks for newest-checkpoint selection, independent task dates, source bytes/mtime preservation, persistent private connection deduplication, unavailable-state replacement, refresh, symlinks, malformed schemas, timestamp/identity/size limits, untrusted text as data, authorization and execution-queue separation. JavaScript syntax and Python compilation passed. Existing-project reads use disposable fixtures in tests. No browser interaction or visual QA was performed.

The updated live coordinator returned HTTP 200 at its existing address and returned the configured project separately from the unchanged local rehearsal and worker registry. The first same-port restart met the prior listener’s socket hold; the server now permits address reuse after shutdown, and a regression test confirms it cannot replace an active listener. The next startup on the same port succeeded. The app reported the preview request queued; no browser render or sign-in was claimed as verified.
