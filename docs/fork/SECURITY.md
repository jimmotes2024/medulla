# Local security and execution boundaries

Version: 0.12.0

## Enforced by this service

- Binds only to `127.0.0.1`; exact Host and same-origin checks reject rebinding and foreign-origin requests. Browser mutations require an Origin matching the service.
- Operator and worker roles are separate. A worker can claim only its own assignments and operate only its own live attempt. Worker credentials cannot read the whole workspace or approve/review work.
- High-entropy operator key and private worker files use mode 0600 inside a mode 0700 state directory. Database stores worker key hashes, not raw worker keys. Credential paths refuse symlinks where created.
- Browser sessions use HttpOnly/SameSite=Strict cookies. The cookie is scoped to loopback HTTP and is not marked Secure; do not reverse-proxy or expose this service remotely. Restart or lock invalidates the in-memory browser session.
- Optional launch links contain a single-use code, not the operator key, and expire after 60 seconds. Browser code removes the fragment before exchanging it. Do not share even these short-lived links.
- No remote assets, telemetry, credentials in access logs, CORS grants, arbitrary file serving or arbitrary command endpoint. A strict Content Security Policy disallows inline/evaluated scripts and framing.
- Artifact content renders through DOM text nodes. Instructions are never executed by the coordinator. JSON sizes, connection count and read time are bounded.
- Approval and acceptance bind to server-held immutable records. Browser-local state cannot approve work. Export omits credential values and hashes.

## Boundaries the operator must understand

The service is a local single-user application, not an OS sandbox. A process running as the same OS user may read that user's private files. External agents retain their own harness permissions; a coordinator token does not confine their shell, filesystem or network access. Do not enable a full-access adapter or point an agent at a sensitive repository under an assumption that this API isolates it.

Cancellation is cooperative. After losing an attempt or credential, the worker must stop before further effects; the service cannot forcibly terminate an unowned runtime. There is no automatic replay of interrupted work. Verify the previous worker stopped before retrying. Production actions, spending, credential access or publication require an independently enforced execution policy; a generic assignment approval is not a deployment receipt.

## Evaluation environment

The built-in worker performs only deterministic analysis of assigned text and accepted artifacts. It makes no model calls and reads no project files. Use it to verify delivery and review behavior before connecting a real agent.

Never commit `.medulla-local/`, tokens, database files, raw customer records or local connection files. Preserve and protect exports according to their contents. Upstream installers and the retained upstream permission defaults are not used by this local runtime.
