# Project OS Workflow

Default phases:

```text
Intake -> Plan -> Research -> Run -> Evaluate -> Promote -> Archive -> Release
```

Rules:

- Read `PROJECT_STATE.md` and this workflow before substantive work.
- Resolve continuation from `runtime/current_session` when set; otherwise use global `runtime/current_branch`, `runtime/current_task`, and `runtime/current_run`.
- A session focus lives under `.project_os/runtime/sessions/<session_id>/` and shadows global pointers only while `runtime/current_session` names that session.
- Load branch context from `.project_os/branches/<branch_id>/branch.json`, `objective.md`, and `context.md`.
- Load task context from `.project_os/branches/<branch_id>/tasks/<task_id>/context_manifest.jsonl`.
- Put generated formal run outputs under `runs/<branch_id>/<run_id>/` by default.
- Treat `.project_os/indexes/*.tsv` as canonical machine registries; root index docs are human-facing derived views.
- State-changing CLI operations use `.project_os/runtime/lock` as an advisory lock.
- Use `plan-recovery` for report-only crash/recovery inspection; it must not replay, roll back, delete tmp files, or remove locks.
- Register runs and results before promotion.
- Promote to `current/` or `release/` only after explicit user approval.
- Append lifecycle events to `.project_os/journals/events.jsonl` for state-changing CLI operations.
- Hooks are reserved but disabled by default; future hooks may observe events and call the CLI, but must not edit canonical state directly.
- Update `PROJECT_STATE.md`, branch handoff, or task `handoff.md` before stopping when project state changed.
