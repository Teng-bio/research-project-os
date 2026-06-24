# Run manifest schema

A formal run must have `RUN_MANIFEST.json`.

Default formal run path:

```text
runs/<branch_id>/<run_id>/RUN_MANIFEST.json
```

Minimal structure:

```json
{
  "run_id": "20260623_153000__nmr_main_qc",
  "branch_id": "main",
  "task_id": "20260623_nmr_main_qc",
  "status": "active",
  "created_at": "2026-06-23T15:30:00+08:00",
  "closed_at": null,
  "code_ref": {"git_commit": null, "dirty": null, "git_available": null},
  "environment": {
    "python": null,
    "python_version": null,
    "platform": null,
    "conda_env": null,
    "virtual_env": null,
    "packages": {},
    "package_capture": {
      "method": "pip freeze",
      "count": 0,
      "raw_line_count": 0,
      "unparsed_count": 0,
      "unparsed_examples": [],
      "freeze_file": "runs/main/<run_id>/docs/pip-freeze.txt",
      "captured_at": null
    }
  },
  "inputs": [],
  "parameters": {},
  "commands": [],
  "outputs": [],
  "metrics": {},
  "result_status": "draft",
  "promoted_to": [],
  "notes": "",
  "summary_file": "RUN_SUMMARY.md"
}
```

Run status values:

```text
active, completed, failed, pending_review, archived, superseded
```

Result status values attached to run outputs:

```text
draft, candidate, accepted, current, superseded, legacy, release
```

Rules:

- Every formal run belongs to exactly one branch and one task.
- `branch_id` must agree with the task's `branch_id`.
- Outputs should live inside the branch-aware run directory unless the project explicitly configures another run root.
- Use `add-run-input`, `add-run-command`, `add-run-output`, `add-run-metric`, `add-run-parameter`, and `capture-run-env` to append structured provenance without hand-editing the manifest.
- Inputs may reference registered assets by `asset_id`; the harness refreshes `.project_os/indexes/asset_usage.tsv` from those references.
- Closing a run writes a detailed `RUN_SUMMARY.md` and must never silently promote results.
- Run environment captures Python executable/version, platform, conda/virtualenv hints, and package snapshots when requested.
- `capture-run-env --pip-freeze` stores parsed package versions in `environment.packages` and writes the raw freeze output to a run-local file by default.
- The default freeze file is `docs/pip-freeze.txt` relative to the run directory; the manifest stores the project-relative path in `environment.package_capture.freeze_file`.
- `RUN_SUMMARY.md` is a human handoff summary derived from `RUN_MANIFEST.json`; the manifest remains the provenance source of truth.

Core provenance commands:

```bash
python scripts/project_os.py add-run-input --root <project> --run-id <run_id> --asset-id <asset_id>
python scripts/project_os.py add-run-command --root <project> --run-id <run_id> --command "..."
python scripts/project_os.py add-run-output --root <project> --run-id <run_id> --path <path>
python scripts/project_os.py add-run-metric --root <project> --run-id <run_id> --name <name> --value <json-or-text>
python scripts/project_os.py add-run-parameter --root <project> --run-id <run_id> --param key=value
python scripts/project_os.py capture-run-env --root <project> --run-id <run_id> --pip-freeze --freeze-file docs/pip-freeze.txt
python scripts/project_os.py close-run --root <project> --run-id <run_id> --status completed
```
