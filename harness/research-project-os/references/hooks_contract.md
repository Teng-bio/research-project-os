# Hooks contract

`research-project-os` treats hooks as an optional automation/reporting layer. The core harness must remain fully usable when hooks are disabled.

## Current status

- Active automatic hook dispatching is **not enabled**.
- A manual, report-only dispatcher is available through:

  ```bash
  python scripts/project_os.py list-hooks --root <project>
  python scripts/project_os.py dispatch-hooks --root <project> --limit 1
  python scripts/project_os.py dispatch-hooks --root <project> --event run.closed --kind reminder
  # if the event source itself is missing, first review:
  python scripts/project_os.py restore-journal --root <project>
  ```

- `.project_os/journals/events.jsonl` is the stable event source for manual hook reports and future hooks.
- `project_os.py` remains the only supported writer for canonical harness state.
- Project templates include `.project_os/spec/hooks.md` and a disabled `hooks:` block in `.project_os/config.yaml` so future implementation can attach without changing the core file contract.
- Manual dispatcher reports may be written under `.project_os/exports/hooks/` with `--write-report`; those reports are generated views only.
- `export-dashboard`, `doctor`, and `validate` may expose hooks config/status advisories, but these surfaces remain inspection/reporting layers and do not enable active automatic hooks.

## Default configuration

```yaml
hooks:
  enabled: false
  mode: disabled
  dispatcher: none
  event_source: .project_os/journals/events.jsonl
  allowed_kinds:
    - session_summary
    - reminder
    - opt_in_maintenance
    - guard
  policy:
    must_call_cli: true
    cannot_write_canonical_state_directly: true
    failure_is_non_blocking_by_default: true
    guard_hooks_require_opt_in: true
```

`enabled: false` means no hook handler is automatically invoked. The current `dispatch-hooks` command is manual and report-only even when this config block says disabled.

## Canonical boundary

Manual/future hooks may:

- observe events from `.project_os/journals/events.jsonl`;
- print summaries or reminders;
- call existing `project_os.py` commands such as `status`, `doctor`, `validate`, `refresh-indexes`, or guarded dry-runs;
- emit non-canonical reports under `.project_os/exports/hooks/` or a future hook log.

Hooks must not:

- edit `.project_os/indexes/*.tsv`, `.project_os/project.json`, runtime pointers, branch/task JSON, run manifests, result rows, or release manifests directly;
- promote, release, archive, delete, or rewrite provenance without the same explicit approval gates as the CLI;
- become required for bootstrap, resume, validation, promotion, release, or migration;
- create a second state store that competes with `.project_os/`.

## Hook categories

| Kind | Purpose | Risk level | Default |
|---|---|---:|---|
| `session_summary` | show current branch/task/run/session focus | low | manual report only |
| `reminder` | suggest next checks after events such as `run.closed` | low | manual report only |
| `opt_in_maintenance` | suggest `doctor`, `validate`, or `refresh-indexes` commands after explicit review | medium | manual report only; no command execution |
| `guard` | add future preflight checks before promotion/release/archive | high | report-only placeholder; future opt-in required |

## Dispatcher input

The manual dispatcher consumes events from `events.jsonl` using the journal vocabulary from `lifecycle_events.md`.

Minimum event payload:

```json
{
  "ts": "2026-06-23T00:00:00Z",
  "event": "run.closed",
  "actor": "cli",
  "branch_id": "main",
  "task_id": "task_...",
  "run_id": "run_...",
  "result_id": "",
  "asset_id": "",
  "release_id": "",
  "detail": {}
}
```

The dispatcher must tolerate missing optional IDs and malformed later events by reporting diagnostics instead of blocking the core workflow. If the event source file is missing, `doctor --repair-plan` should point to `restore-journal`; that command only recreates the missing file and appends `journal.restored`.

## Handler output

Handlers should return a small JSON object or a plain text summary:

```json
{
  "hook_id": "session-summary",
  "kind": "session_summary",
  "event": "session.changed",
  "status": "ok",
  "message": "Current branch main; no active run.",
  "suggested_commands": [
    "python scripts/project_os.py status --root <project>"
  ]
}
```

Handler failures should be non-blocking by default. Guard hooks are the only category that may block an operation, and only after explicit project/user opt-in.

## Implementation order

1. Keep event names and event journal stable.
2. Keep CLI commands idempotent enough for hooks to call safely.
3. ✅ Add read-only/manual session-summary reports.
4. ✅ Add manual reminder reports.
5. ✅ Add opt-in maintenance command suggestions without executing them.
6. Keep active automatic dispatch disabled until real-project dogfooding proves the contract.
7. Add guard hooks last, with explicit confirmation and clear bypass behavior.
