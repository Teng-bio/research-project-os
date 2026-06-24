# Run provenance policy

Every formal run should have `RUN_MANIFEST.json` with branch_id, task_id, inputs, parameters, code reference, environment, commands, outputs, metrics, and status.

Use CLI commands such as `add-run-input`, `add-run-command`, `add-run-output`, `add-run-metric`, `add-run-parameter`, and `capture-run-env` rather than hand-editing provenance when possible.

When package provenance is needed, run:

```bash
python scripts/project_os.py capture-run-env --root <project> --run-id <run_id> --pip-freeze --freeze-file docs/pip-freeze.txt
```

The freeze file is stored relative to the run directory by default and its project-relative path is recorded in `RUN_MANIFEST.json` under `environment.package_capture.freeze_file`.

Closing a run writes a human-readable `RUN_SUMMARY.md` with identity, counts, parameters, inputs, commands, outputs, metrics, promoted targets, environment, package sample, and notes. `RUN_MANIFEST.json` remains the source of truth.
