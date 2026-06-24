# Harness contract

`research-project-os` is a repository-local harness for long-running research and analysis projects.

## State layers

| Layer | Purpose | Files | Source-of-truth status |
|---|---|---|---|
| Machine registry | queryable branch/task/run/result/asset/release rows | `.project_os/indexes/*.tsv` | canonical |
| Project identity | project id, schema version, profile, default branch | `.project_os/project.json` | canonical |
| Event journal | append-only lifecycle audit stream | `.project_os/journals/events.jsonl` | canonical event source |
| Runtime focus | current branch/task/run pointers, optionally scoped by session | `.project_os/runtime/current_session`, global `current_branch`/`current_task`/`current_run`, and `.project_os/runtime/sessions/<session_id>/current_*` | canonical runtime pointers |
| Branch/task context | branch workspace and task manifests | `.project_os/branches/<branch_id>/...` | canonical for branch/task context |
| Run provenance | actual commands, inputs, parameters, environment, outputs | `runs/<branch_id>/<run_id>/RUN_MANIFEST.json` or another project-approved branch-aware run root | canonical for the run |
| Human handoff | concise project status and entry points | `PROJECT_STATE.md`, `RESULTS_INDEX.md`, `DATA_ASSETS.md`, `RUNS_INDEX.tsv`, `DECISIONS.md` | human-facing derived/handoff views |
| Release package | copied accepted/current artifacts with manifest and checksums | `release/<release_id>/README.md`, `MANIFEST.tsv`, `CHECKSUMS.tsv` | package output; provenance remains canonical elsewhere |
| Generated display | dashboard JSON/HTML/SQLite exports | `.project_os/exports/` | generated view only |
| Deferred automation | future hooks observing lifecycle events | `.project_os/spec/hooks.md`, `hooks:` block in `.project_os/config.yaml` | contract only; disabled by default |

The most important rule is:

```text
.project_os/indexes/*.tsv + .project_os/project.json + .project_os/journals/events.jsonl
  = canonical machine state

root PROJECT_STATE / RESULTS_INDEX / DATA_ASSETS / RUNS_INDEX
  = human handoff or derived view
```

Generated display files are never the source of truth unless a project explicitly changes this policy. The default generated dashboard files are:

```text
.project_os/exports/dashboard.json
.project_os/exports/dashboard.html
.project_os/exports/dashboard.sqlite   # optional
```

Create them with `project_os.py export-dashboard`; canonical state remains `.project_os/indexes/*.tsv`, `.project_os/project.json`, `.project_os/journals/events.jsonl`, runtime pointers, and branch/task/run/result manifests.

Dashboard exports may include derived graph nodes/edges and derived session-focus summaries, including session nodes and `focus_branch` / `focus_task` / `focus_run` edges. These make the current work context visible, but they are still generated inspection views and must not be edited as state.

Dashboard exports may include derived current-result and promotion-audit summaries based on `results.tsv` and `current/` targets. In SQLite exports these appear as `current_results_status`, `current_results`, `current_result_branch_counts`, and `promotion_audit`. These tables are for inspection only; promotion still goes through `promote-result` and explicit approval gates.

Dashboard exports may also include a derived `session_cleanup` candidate summary for closed sessions and, when SQLite is requested, a `session_cleanup_candidates` table. These are advisory inspection views only.

Session cleanup reports are also generated inspection views:

```text
.project_os/exports/session_cleanup/session_cleanup_plan_<timestamp>.json
```

They identify paused/closed session candidates for human review, but do not delete, move, archive, or rewrite `.project_os/runtime/sessions/<session_id>/`.

Recovery inspection reports are generated inspection views:

```text
.project_os/exports/recovery/recovery_plan_<timestamp>.json
```

They identify possible crash/recovery candidates such as stale advisory locks, atomic-write `*.tmp` leftovers, malformed journal lines, missing required harness paths, pointer drift, manifest/index drift, and stale generated views. They do not replay events, roll back operations, delete tmp files, remove locks, or rewrite canonical state.

Hooks are also not canonical state. The default contract keeps hooks disabled; future handlers may observe lifecycle events and call `project_os.py`, but must not edit canonical files directly.

If the event journal is missing, `project_os.py restore-journal` can create `.project_os/journals/events.jsonl` after review. It appends a `journal.restored` event and does not reconstruct historical lifecycle coverage.

## Required invariant

A future agent must be able to answer these questions from files without chat history:

1. What is the current active task?
2. Which context files should be loaded for that task?
3. Which run is active or most recent?
4. Which results are draft, candidate, accepted, current, legacy, or release?
5. Which data assets and reference resources were used?
6. What must be done next?
7. Which release packages were built from which accepted/current results?

## Consistency and repair invariant

`doctor` and `validate` should detect broken pointers, missing required files, stale derived views, dependency/replacement cycles, asset checksum drift, and release package breakage.

`doctor --repair-plan` may propose commands, but it must not perform destructive or provenance-changing operations.

`plan-recovery` is a separate report-only crash/recovery inspection command. `doctor --repair-plan` may point to it when recovery candidates exist, but neither command may perform crash replay, rollback, tmp deletion, or lock removal.

## Branch-first invariant

Branch/workstream is both:

1. a row in `.project_os/indexes/branches.tsv`
2. a physical workspace under `.project_os/branches/<branch_id>/`

Tasks live under the branch workspace, and formal runs should default to `runs/<branch_id>/<run_id>/`.

## Session runtime invariant

Global runtime pointers remain valid and are used when `.project_os/runtime/current_session` is empty.

When `current_session` names a session, the active focus is resolved from:

```text
.project_os/runtime/sessions/<session_id>/current_branch
.project_os/runtime/sessions/<session_id>/current_task
.project_os/runtime/sessions/<session_id>/current_run
```

Session pointers shadow global pointers; they do not create new branch/task/run identities. Every session pointer must still reference canonical branch/task/run state.

Session archive/GC policy is report-first: `plan-session-cleanup` may generate candidate reports for closed or paused sessions, but physical cleanup is deferred and must remain explicit, reviewed, validation-gated, and non-canonical if added later.

## What the harness must not do

- Do not replace a project-specific scientific, analysis, or engineering plan.
- Do not silently promote outputs to accepted/current.
- Do not treat old filenames such as `final` as proof of acceptance.
- Do not use chat memory as the only record of task state.
- Do not execute repair plans automatically when they change provenance, acceptance, current outputs, releases, or checksums.
