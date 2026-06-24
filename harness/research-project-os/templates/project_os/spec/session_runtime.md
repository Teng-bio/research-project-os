# Session runtime policy

Default operation uses global runtime pointers:

```text
.project_os/runtime/current_branch
.project_os/runtime/current_task
.project_os/runtime/current_run
```

For parallel workstreams, named sessions may shadow those pointers:

```text
.project_os/runtime/current_session
.project_os/runtime/sessions/<session_id>/current_branch
.project_os/runtime/sessions/<session_id>/current_task
.project_os/runtime/sessions/<session_id>/current_run
.project_os/runtime/sessions/<session_id>/session.json
```

If `current_session` is empty, CLI commands use the global pointers. If it names a session, pointer reads/writes use that session directory. Session pointers must still reference existing branch/task/run objects and are checked by `validate` / `doctor`.

Session lifecycle states are `active`, `paused`, and `closed`.

- `pause-session` marks a session paused and clears it from `current_session` if it is active.
- `resume-session` marks a paused session active again; `--set-current` may also switch the runtime focus to it.
- `close-session` permanently closes a session and clears it if needed.
- `plan-session-cleanup` generates a dry-run/report-only candidate list for closed or paused sessions; it does not delete, move, or rewrite session directories.

Paused and closed sessions must not be used as the active `current_session`. Sessions are focus overlays only; they do not create branch/task/run/result identities and do not bypass promotion or release approval gates.

Session cleanup reports, when written, live under `.project_os/exports/session_cleanup/` and are generated inspection views only. Any future physical session archive/GC operation must remain explicit, reviewed, validation-gated, and non-canonical.
