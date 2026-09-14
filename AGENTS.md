# Medulla local fork

This is Jim's development fork. Product code belongs in orchestrator/; upstream documentation remains in docs/ and gitbooks/. The upstream documentation-only restriction is superseded for this fork.

- Keep development isolated from existing agent sessions, Agora, repositories, credentials, watchers and services. Never discover or control those automatically.
- The coordinator is local only. External agents join explicitly with scoped credentials. No broad permission bypass, arbitrary shell endpoint, hosted orchestration, or automatic model calls.
- Keep task ownership, delivery, START, artifacts and human acceptance distinct. Do not infer work from process existence or a delivery receipt.
- Run the local test suite before commit; record real limitations. Update VERSION, changelog and fork documentation with meaningful changes.
- Preserve upstream material and provenance. Do not modify upstream installers or publish releases through their pipeline.
- Work on axiom/local-orchestrator; push only to jimmotes2024/medulla. Do not force-push or alter upstream.
- Never commit runtime state, tokens, private project details, or local absolute paths. Reference example agents as examples, never as live telemetry.
- Keep modules focused. Use Python standard library for the local runtime and native HTML/CSS/JavaScript for the console. Do not add dependencies without an identified need.

Verification: cd orchestrator && python3 -m unittest discover -s tests -v; node --check orchestrator/medulla_local/web/app.js from repository root.
