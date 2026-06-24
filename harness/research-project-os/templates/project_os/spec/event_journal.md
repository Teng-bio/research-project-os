# Event journal policy

State-changing CLI commands append compact JSON events to `.project_os/journals/events.jsonl`.

This journal is the stable event source for manual hook reports, dashboards, repair tooling, audit summaries, and future opt-in automation. Active automatic hooks are deferred and disabled by default. Current manual hook reports may read this journal and suggest `project_os.py` commands, but they do not execute those commands or edit canonical state directly. Future hooks may observe this journal and call `project_os.py`, but they must not edit canonical state directly.

If `events.jsonl` is missing, use `project_os.py restore-journal` as a dry-run first, then `--apply --approved` only after review. This command creates the missing journal and appends `journal.restored`; it does not overwrite an existing journal or reconstruct historical lifecycle events.

`project_os.py plan-recovery --write-report` writes only a generated inspection report and does not append lifecycle events, because recovery reports must not mutate canonical state.
