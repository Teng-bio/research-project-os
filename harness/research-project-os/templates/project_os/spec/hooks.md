# Hooks policy

Hooks are optional automation/reporting helpers and are disabled by default for automatic execution.

Current project contract:

- `.project_os/journals/events.jsonl` is the stable event source for manual hook reports and future hooks.
- The core harness must work without hooks.
- Manual hook reports may be generated with `project_os.py list-hooks` and `project_os.py dispatch-hooks`.
- Hook reports may suggest `project_os.py` commands, but current manual dispatch does not execute them.
- Future active hooks may observe events and call `project_os.py`.
- Hooks must not edit canonical state files directly.
- Guard hooks for promotion, release, archive, or destructive maintenance must be explicit opt-in.

Default reserved configuration lives in `.project_os/config.yaml` under `hooks:`.

Generated hook reports, when requested, live under `.project_os/exports/hooks/` and are derived views only.
