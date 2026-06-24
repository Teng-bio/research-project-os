# Result index schema

`.project_os/indexes/results.tsv` and task `result_links.tsv` use this minimal schema:

```text
result_id	branch_id	task_id	run_id	status	type	path	title	created_at	accepted_at	promoted_to	replaced_by	notes
```

Allowed result statuses:

```text
draft, candidate, accepted, current, superseded, legacy, release
```

Rules:

- Register generated outputs as `draft` or `candidate` first.
- `accepted` or `current` requires explicit user approval. Use `accept-result --approved` for acceptance and `promote-result` dry-run before `--apply --approved` for current promotion.
- Root `RESULTS_INDEX.md` is the human-facing result entry point and should summarize accepted/candidate/legacy outputs.
- `current/` should contain promoted pointers/copies only, never independent ad-hoc versions.
- Branch-level current results may live under `current/branches/<branch_id>/`.
- Project-level current results may live under `current/project/`.
- Every result must retain `branch_id`, `task_id`, and `run_id` so provenance is reconstructable from files.
- `show-current` is a derived view over `results.tsv` and promoted `current/` targets. It does not create or edit canonical state.
- `show-current --scope project` shows project-level current targets under `current/project/`.
- `show-current --scope branch --branch-id <branch_id>` shows branch-level current targets under `current/branches/<branch_id>/`, plus branch-owned `status=current` rows that lack an explicit branch target for migration compatibility.
- `show-current --audit` reports missing current targets, duplicate current targets, and cross-branch promotions for review.

Core commands:

```bash
python scripts/project_os.py register-result --root <project> --run-id <run_id> --path <path> --status candidate
python scripts/project_os.py accept-result --root <project> --result-id <result_id> --approved
python scripts/project_os.py promote-result --root <project> --result-id <result_id> --to current/branches/<branch_id>/<file> --apply --approved
python scripts/project_os.py supersede-result --root <project> --result-id <old_id> --replaced-by <new_id> --approved
python scripts/project_os.py show-current --root <project> --branch-id <branch_id>
python scripts/project_os.py show-current --root <project> --scope project --audit
```
