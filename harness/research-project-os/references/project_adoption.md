# Project adoption workflow

Use this when adding `.project_os/` to an existing project.

## Choose the entry path

Use different commands depending on what already exists:

| Project condition | First command | Why |
|---|---|---|
| No `.project_os/` yet | `project_os.py init --root <project>` dry-run, then `--apply` after review | Creates a fresh branch-first harness without moving existing analysis files. |
| Old flat harness exists (`.project_os/tasks/<task_id>/`, `runs/<run_id>/`) | `project_os.py migrate-branch-first --root <project>` dry-run | Explains task/run movement, scaffold repairs, path rewrites, and conflicts before any adoption. |
| Partial branch-first harness exists but lacks anchors/spec/root entry files | `project_os.py migrate-branch-first --root <project>` dry-run | Fills missing non-destructive scaffold and upgrades indexes so strict `validate` can pass. |
| Mixed or hand-edited manifests | dry-run only until `diagnostics.summary.safe_to_apply=true` | Prevents silent workstream merging or provenance loss. |

Do not run `init --apply` as a blind fix for an old flat harness. Use migration dry-run first so branch mapping, target existence, and provenance rewrites are visible. If only `.project_os/journals/events.jsonl` is missing in an otherwise initialized project, prefer `restore-journal` dry-run and then reviewed `--apply --approved` rather than reinitializing the harness.

## Fresh adoption steps

1. Run `project_os.py init --root <project>` without `--apply` to preview.
2. Read the existing `PROJECT_STATE.md`, `AGENTS.md`, `DATA_ASSETS.md`, `RESULTS_INDEX.md`, `RUNS_INDEX.tsv`, and `DECISIONS.md` when present.
3. Run `project_os.py init --root <project> --apply` only after confirming the new files will not overwrite existing work.
4. Create one task representing the active workstream.
5. Add existing authoritative plans and root docs to that task's `context_manifest.jsonl`.
6. Set runtime pointers with `set-current-task` and, only when known, `current_run`.
7. Run `validate` and fix errors before using the harness as the continuation source.

## Flat layout migration

Older harness prototypes may have used flat paths such as `.project_os/tasks/<task_id>/` and `runs/<run_id>/`.
Some older harnesses may also have `.project_os/workflow.md` but lack the later branch-first anchors:

- `.project_os/project.json`
- `.project_os/journals/events.jsonl`
- `.project_os/branches/<branch_id>/branch.json`
- `.project_os/spec/*.md`
- root human entry files such as `PROJECT_STATE.md` and `DECISIONS.md`
- `current/project/`, `current/branches/<branch_id>/`, and `release/`
- full branch-aware index headers
- `.project_os/indexes/asset_usage.tsv`
- `.project_os/indexes/releases.tsv`

Use the guarded migration command:

```bash
python scripts/project_os.py migrate-branch-first --root <project>
python scripts/project_os.py migrate-branch-first --root <project> --apply --mode move
```

The command defaults to dry-run. Applying it maps flat tasks to `.project_os/branches/<branch_id>/tasks/<task_id>/`, maps flat runs to `runs/<branch_id>/<run_id>/`, and patches missing `branch_id` / required task context files where possible.

By default, `--branch-id` is the single target branch for unannotated old flat layouts. If old `task.json` / `RUN_MANIFEST.json` files already contain trustworthy `branch_id` values from multiple workstreams, run dry-run with:

```bash
python scripts/project_os.py migrate-branch-first --root <project> --preserve-manifest-branches
```

This explicitly preserves manifest branch IDs and plans separate physical directories such as `.project_os/branches/<legacy_branch>/tasks/...` and `runs/<legacy_branch>/<run_id>/`. Without this flag, a manifest branch that disagrees with `--branch-id` remains a blocking mismatch so different workstreams are not silently merged.

It also creates missing non-destructive adoption scaffold files/directories, including project identity, event journal, spec templates, runtime pointer files, root human entry files, branch subdirectories, current directories, and release directories. It upgrades older index headers to the branch-aware schema, creates missing index files, and patches missing `branch_id`, `task_id`, `run_id`, `promoted_to`, and `replaced_by` fields where possible. During run moves it rewrites legacy paths in `results.tsv`, task `run_links.tsv` / `result_links.tsv`, and run manifest input/output/promoted paths so migrated artifacts remain discoverable. It also preserves older run-manifest provenance shapes by normalizing legacy dict/string/list `inputs`, `commands`, `outputs`, `promoted`, and `key_results` fields into the current structured manifest fields instead of dropping them. It does not delete historical runs/results.

Dry-run output includes possible link-table repairs, task/run-manifest field repairs, legacy provenance-shape normalization such as `normalize_inputs_shape` / `normalize_outputs_shape`, and a `diagnostics` block. For scriptability, `summary`, `conflicts`, `warnings`, and `safe_to_apply` are also mirrored directly under `dry_run_migration` and `migrated_branch_first`:

- `summary.safe_to_apply`: true only when no blocking conflict was detected.
- `summary.scaffold_repairs`: missing non-destructive adoption scaffold files/directories that would be created.
- `summary.branch_repairs`: missing or incomplete branch workspace records that would be created/repaired.
- `summary.manifest_conflicts`: malformed or hand-edited task/run/branch manifests that block safe apply.
- `conflicts`: target directories already exist, duplicate/conflicting `task_id` / `run_id` / `result_id`, malformed manifests, task/run ID mismatches between directory names and manifests, task/run branch mismatches, run/task branch ownership mismatches, invalid legacy branch IDs, and other apply blockers.
- `warnings`: missing result paths, missing asset paths, result rows whose task/run provenance cannot be inferred, run manifests that point to missing tasks, or flat run paths that could not be mapped.
- `planned_branches`: branch IDs that would be created or used by the migration plan; this is most important when `--preserve-manifest-branches` is enabled.

Treat `status: exists` / `target_exists` as a conflict that requires manual review or an explicit `--replace`. Do not use `--replace` until the target contents have been inspected.

If a result artifact lives outside `runs/`, migration can still backfill provenance when a task-local `result_links.tsv` row supplies the `run_id`. External artifact paths should not be rewritten unless they are covered by an explicit flat-run path map.

For real projects, prefer this safety pattern:

1. Run dry-run on the original project and review `diagnostics.safe_to_apply`.
2. Copy the project to `/tmp` or another scratch location.
3. Run `migrate-branch-first --apply --mode copy` on the copy.
4. Optionally run `--mode move` on a fresh copy when validating physical move behavior; an empty legacy `.project_os/tasks/` container may remain and should be treated as benign unless a future explicit cleanup planner removes it.
5. Require `validate` to return `0 errors / 0 warnings`.
6. Require `doctor` to return `ok=true`. Adapter warnings should point to `install-adapters --platforms codex|claude --apply` and remain approval-gated.
7. Require `start` to resolve the expected current branch/task/run before applying to the original.

## Existing project rule

For an existing scientific project, the harness should point to current plans instead of replacing them. If a project already has a planning hierarchy, encode that hierarchy in `.project_os/spec/project_rules.md` and task context manifests.
