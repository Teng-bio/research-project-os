# Branch schema

Branch/workstream is a first-class harness object.

## Physical layout

Each branch gets a physical workspace:

```text
.project_os/branches/<branch_id>/
```

Required files/directories:

```text
branch.json
objective.md
context.md
handoff.md
decisions.md
research/
notes/
tasks/
```

Tasks for the branch live under:

```text
.project_os/branches/<branch_id>/tasks/<task_id>/
```

Formal runs for the branch default to:

```text
runs/<branch_id>/<run_id>/
```

Branch-level current accepted outputs may be promoted under:

```text
current/branches/<branch_id>/
```

## Global branch index

Canonical file:

```text
.project_os/indexes/branches.tsv
```

Header:

```text
branch_id	status	parent_branch_id	title	branch_path	task_root	run_root	current_root	git_branch	created_at	closed_at	notes
```

Allowed status values:

```text
active, paused, completed, archived, abandoned
```

## Required `branch.json` fields

```json
{
  "branch_id": "main",
  "title": "Main analysis line",
  "status": "active",
  "parent_branch_id": "",
  "git_branch": null,
  "branch_path": ".project_os/branches/main",
  "task_root": ".project_os/branches/main/tasks",
  "run_root": "runs/main",
  "current_root": "current/branches/main",
  "created_at": "2026-06-23T00:00:00+08:00",
  "closed_at": null,
  "objective_file": "objective.md",
  "context_file": "context.md",
  "handoff_file": "handoff.md",
  "notes": ""
}
```

## Rules

- Every task belongs to exactly one branch.
- Every formal run belongs to exactly one branch.
- Every result belongs to exactly one branch.
- Branch archive must not delete tasks, runs, or results.
- Harness branch is not required to equal Git branch, but `git_branch` may be recorded when useful.
