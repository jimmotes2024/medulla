# Read-only project connections

Version: 0.12.1

The Overview connects an existing cockpit to the human workspace while its agents continue using their existing tools. Observed projects are distinct from local executable projects. There is no import into SQLite, worker enrollment, assignment dispatch, source mutation or message sending.

## Source contract

The operator runs `connect-cockpit --directory PATH --name NAME` locally. PATH is the instrument-panel directory, not the HTML file. The command verifies both source files before atomically recording the connection in the coordinator's private `sources.json`. Reconnecting the same canonical directory updates its display name instead of duplicating it.

- `tasks/TASKS.v1.json`: `tasks.v1` schema; dated generation and task updates; unique task IDs with recorded status and owner.
- `checkpoints/gates.v1.json`: `kredo-panel-gate-disposition.v1` schema; `judge_diagnostics.owned_*` records with timezone-qualified `as_of_cutoff_utc` timestamps.

The latest eligible checkpoint is chosen by timestamp, not filename or object order. Focus, update cards, decision owner and next step are displayed from that record. Each task retains its original ID, owner, status and timestamp. A task list older than the checkpoint gets an explicit warning; neither age nor a listed owner proves current agent execution. Sources are not automatically semantically reconciled. A source author must update its records when a decision changes.

## Local behavior

An authenticated `/api/state` response includes `observed.projects` separately from executable `projects` and `tasks`. The console opens on Overview; Work retains the coordinator's own assignments. Only operator authentication can read observed project content. Worker credentials cannot read it, approve an observed task, or claim it. Existing record export covers coordinator records only.

Reads are demand-driven by the existing visible-console refresh, cached for five seconds, and serialized. At most 20 connections, 2,000 tasks per source and 8 MiB per JSON file are accepted. The reader opens only the two fixed filenames and refuses symlink files or child directories, nonregular files, over-limit reads, invalid timestamps and incompatible schemas. It records hashes of the bytes actually read. The two sources are separate dated snapshots, not an atomic cross-file transaction or tamper-proof attestation.

After cache expiry, missing or malformed sources replace the prior project data with an explicit unavailable state. The UI does not silently continue presenting old content as current. One failed source does not hide the local work queue or healthy connections.

The original cockpit path is available under Source details. The service does not expose an arbitrary file endpoint or host the cockpit's executable HTML/JavaScript under its authenticated origin. Local source paths, content and configuration remain out of the public repository.
