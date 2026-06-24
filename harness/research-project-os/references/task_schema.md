# Task schema

Task directories live under the branch workspace:

```text
.project_os/branches/<branch_id>/tasks/<task_id>/
```

Required files:

```text
task.json
objective.md
context.md
context_manifest.jsonl
decisions.md
run_links.tsv
result_links.tsv
handoff.md
research/
```

Required `task.json` fields:

```json
{
  "task_id": "20260623_nmr_main_qc",
  "title": "NMR main-line QC pass",
  "status": "active",
  "kind": "analysis",
  "stage": "Intake",
  "branch_id": "main",
  "parent_task_id": null,
  "task_path": ".project_os/branches/main/tasks/20260623_nmr_main_qc",
  "created_at": "2026-06-23T20:00:00+08:00",
  "updated_at": "2026-06-23T20:00:00+08:00",
  "owner": "",
  "priority": "normal",
  "objective_file": "objective.md",
  "context_file": "context.md",
  "context_manifest": "context_manifest.jsonl",
  "handoff_file": "handoff.md",
  "notes": ""
}
```

Allowed status values:

```text
active, paused, blocked, completed, archived, superseded
```

Allowed `stage` values:

```text
Intake, Plan, Research, Run, Evaluate, Promote, Archive, Release
```

Rules:

- Every task belongs to exactly one branch.
- `task_path` should match the branch-first layout.
- `depends_on.tasks[]` and `depends_on.results[]` are DAG references; no self-dependency or cycles.
- Use `update-task`, `update-task-stage`, `close-task`, `add-dependency`, `remove-dependency`, `add-context`, `remove-context`, and `update-handoff` for lifecycle/context changes instead of hand-editing when possible.
- Task-local `run_links.tsv` and `result_links.tsv` are branch-local convenience indexes, not replacements for global indexes.

Core commands:

```bash
python scripts/project_os.py update-task --root <project> --task-id <task_id> --owner <owner> --priority high
python scripts/project_os.py update-task-stage --root <project> --task-id <task_id> --stage Run
python scripts/project_os.py add-dependency --root <project> --task-id <task_id> --depends-on-task <upstream_task_id>
python scripts/project_os.py remove-dependency --root <project> --task-id <task_id> --depends-on-result <result_id>
python scripts/project_os.py add-context --root <project> --task-id <task_id> --path <path> --purpose "why this context matters"
python scripts/project_os.py remove-context --root <project> --task-id <task_id> --path <path>
python scripts/project_os.py update-handoff --root <project> --scope task --task-id <task_id> --message "..."
python scripts/project_os.py close-task --root <project> --task-id <task_id> --status completed
```
