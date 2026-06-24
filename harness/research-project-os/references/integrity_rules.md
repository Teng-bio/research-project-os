# Integrity rules

These rules define how `doctor`, `validate`, and future repair tooling classify project state.

## Source of truth

- `.project_os/indexes/*.tsv`, `.project_os/project.json`, and `.project_os/journals/events.jsonl` are canonical machine state.
- `RUNS_INDEX.tsv`, `RESULTS_INDEX.md`, and `DATA_ASSETS.md` are derived human views.
- `current/` and `release/` contain promoted/copied artifacts, but provenance remains in indexes and run manifests.

## Journal / snapshot audit rules

- Every lifecycle event that names a branch/task/run/result/asset/release should reference an object that still exists in the current snapshot, unless historical cleanup has been explicitly documented.
- Every non-legacy branch/task/run/result/asset/release row in the current snapshot should have event coverage in `events.jsonl`.
- Rows created before a `project.adopted` event may be treated as adopted legacy state and should not be warned solely for missing original creation events.
- `validate` / `doctor` report missing event coverage as warnings, not errors, because journal repair is provenance-sensitive.
- Repair suggestions should point to state review / decision recording; agents should not hand-edit lifecycle events to silence warnings.
- If the journal file itself is missing, `doctor --repair-plan` may suggest approval-gated `restore-journal --apply --approved`; this only creates the missing file and records `journal.restored`, not historical reconstruction.

## Branch rules

- `current_branch` must point to an existing branch whose status is not `archived` or `abandoned`.
- If `.project_os/runtime/current_session` is set, it must point to an existing session directory with valid session pointers.
- Session `current_branch` / `current_task` / `current_run` pointers must reference the same canonical branch/task/run objects as global pointers would; sessions do not create separate object identities.
- An archived/abandoned branch should not retain active tasks or active/pending runs.
- Cross-branch promotion is allowed only when visible in `results.tsv.promoted_to`; `doctor` reports it as an audit warning.

## Task rules

- `task_id` is project-wide unique.
- A task belongs to exactly one branch.
- `depends_on.tasks[]` and `depends_on.results[]` form a DAG:
  - no self-dependency
  - no task dependency cycles
  - referenced tasks/results should exist
- A task marked `superseded` or `archived` should not own a `current` result without an explicit review note.

## Run rules

- `run_id` is project-wide unique.
- A formal run must have `RUN_MANIFEST.json` under a branch-aware run root such as `runs/<branch_id>/<run_id>/`.
- Closing a run writes `RUN_SUMMARY.md` and must not promote results automatically.
- Run inputs may reference `asset_id`; `asset_usage.tsv` should be refreshed from run manifests.

## Result rules

- `result_id` is project-wide unique.
- `accepted`, `current`, and `release` states require explicit approval.
- `replaced_by` links must not point to the same result, must not form cycles, and should point to an existing result.
- Promotion targets must live under `current/`.

## Asset rules

- Raw/reference/data assets are immutable by default.
- Immutable assets with checksums should not drift; checksum drift is a warning requiring human review.
- Missing local asset paths should be marked `unavailable` or repaired.
- `asset_locations.tsv` is the multi-location registry for externalized assets; each canonical asset should have a `role=primary` location row.
- `assets.tsv.path` should match the `role=primary` location path when a primary location row exists.
- Hard-link semantics are forbidden; portability must rely on `asset_id` + `asset_locations.tsv`.

## Release rules

- Release packages should include `README.md`, `MANIFEST.tsv`, `CHECKSUMS.tsv`, and copied artifacts.
- `validate-release` verifies release files and checksums.
- Release build defaults to dry-run; apply requires explicit `--apply`.

## Repair-plan policy

`doctor --repair-plan` may suggest commands, but it must not execute destructive or provenance-changing operations. Any command that changes acceptance, current promotion, release contents, checksum registration, or migration still requires explicit user approval.

## Generated dashboard policy

`export-dashboard` is a derived inspection view. It may expose graph, session, current-result, promotion-audit, hook, cleanup, and recovery summaries in JSON/HTML/SQLite, but it must not become an editable state store.

Current-result and promotion-audit dashboard tables are derived from `results.tsv`, `current/` targets, and the same audit helpers used by `show-current --audit`; they do not authorize promotion, repair duplicate targets, or mark results accepted/current.

## Recovery inspection policy

`plan-recovery` is report-only. It may inspect and report:

- stale advisory lock candidates under `.project_os/runtime/lock`
- atomic-write tmp leftovers such as `*.tmp` / `.tmp.*`
- malformed `events.jsonl` lines
- missing required harness files or directories
- runtime pointers that reference missing branch/task/run/session objects
- branch/task/run manifest and index drift
- stale root derived views or generated dashboard exports

It must not delete tmp files, remove locks, rewrite indexes, repair pointers, replay journals, roll back operations, or synthesize lifecycle events.

`doctor --repair-plan` may suggest `plan-recovery --write-report` as an advisory step when candidates exist. That suggestion is not an automatic repair and should not make otherwise valid closed/session/export states fail validation.
