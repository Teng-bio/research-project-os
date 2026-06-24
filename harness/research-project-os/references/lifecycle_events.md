# Lifecycle events

These event names define stable extension points for audit tooling, future hooks, dashboards, and plugin automation.

The core harness must work **without** hooks. State-changing CLI commands append these events to `.project_os/journals/events.jsonl`; the current manual dispatcher can read this journal for report-only summaries, while active automatic hook handlers remain deferred.

See `hooks_contract.md` for the default-disabled dispatcher/handler contract and current manual report-only commands.

## Event list

```text
project.initialized
project.adopted
journal.restored
branch.created
branch.changed
branch.archived
task.created
task.changed
task.closed
run.created
run.updated
run.closed
session.created
session.changed
session.paused
session.resumed
session.closed
result.registered
result.accepted
result.promoted
result.superseded
asset.registered
asset.updated
release.created
release.validated
decision.recorded
handoff.updated
state.updated
export.created
```

## Intended future use

- Manual hook reports may observe these events and suggest existing CLI commands without executing them.
- Future active hooks may later observe these events and call existing CLI commands after explicit opt-in.
- Plugins may expose these events in UI flows or bundled automation.
- Dashboards may use event logs or command outputs derived from these names.
- Subskills should use the same event vocabulary instead of inventing new lifecycle names.

## Current phase rule

Keep the append-only event journal stable and keep manual hook dispatch report-only; do **not** implement active automatic hook logic yet. First stabilize:

- file layout
- CLI semantics
- indexes
- state transitions
- journal append/read semantics

Only after that should hook handlers subscribe to the journal.

## Implemented command sources

Current CLI state-changing commands emit the matching lifecycle events for:

- branch/task/run/result lifecycle changes
- sessionized runtime focus lifecycle changes
- asset registration and updates
- asset externalization state changes still emit `asset.registered` / `asset.updated`; report-only externalization planning/verification commands do not append lifecycle events
- decision and handoff updates
- release creation and optional validation recording
- generated export creation (`export.created`)
- missing event-journal restoration (`journal.restored`)

Report-only recovery inspection (`plan-recovery --write-report`) does not append a lifecycle event because recovery reports are generated views and must not mutate canonical state.

`record-decision` also appends `.project_os/journals/decisions.jsonl` for decision listing, but `events.jsonl` remains the stable hook/dashboard event source.

## Journal restoration

If `.project_os/journals/events.jsonl` is missing, use `restore-journal` as a dry-run first and apply only after review with `--apply --approved`. The command creates the missing file and appends `journal.restored`; it does not overwrite an existing journal or synthesize historical events. Remaining snapshot-coverage warnings should be handled by provenance review / decisions rather than hand-editing the journal.
