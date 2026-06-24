# Workflow phases

The default research workflow is:

```text
Intake -> Plan -> Research -> Run -> Evaluate -> Promote -> Archive -> Release
```

## Phase rules

### Intake

Read existing project state, root entry docs, and `.project_os/config.yaml` if present. For existing projects, first adopt and index; do not reorganize.

### Plan

Create or select a branch-local task directory. Link existing authoritative plans through `context_manifest.jsonl`; do not create a competing plan unless the user explicitly asks to replace the old plan.

### Research

Save supporting reports under `.project_os/branches/<branch_id>/tasks/<task_id>/research/` or branch-local research folders. Record durable decisions in task `decisions.md`, branch `decisions.md`, or root `DECISIONS.md`.

### Run

Create a timestamped branch-aware run and `RUN_MANIFEST.json`. Default path is `runs/<branch_id>/<run_id>/`. Record inputs, parameters, code reference, environment, commands, outputs, and status.

### Evaluate

Compare outputs against acceptance checks. Register useful outputs as draft or candidate results.

### Promote

Only after explicit user approval, copy or link selected outputs to `current/branches/<branch_id>/` or `current/project/` and update `RESULTS_INDEX.md`.

### Archive

Mark superseded/legacy status in indexes. Do not delete.

### Release

Package accepted/current outputs with manifest and checksums under `release/<release_id>/`.
Use `build-release` as a dry-run first; apply only after the selected result IDs are explicit. A release package should include `README.md`, `MANIFEST.tsv`, `CHECKSUMS.tsv`, and copied artifacts.
