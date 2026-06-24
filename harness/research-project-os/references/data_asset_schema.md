# Data asset schema

`.project_os/indexes/assets.tsv` mirrors concise asset rows and should stay compatible with the human asset view (`DATA_ASSETS.md` when it is managed by the harness, otherwise `.project_os/exports/views/DATA_ASSETS.generated.md`).

Header:

```text
asset_id	kind	path	version	source_url	source_note	immutable	status	registered_at	checksum	notes
```

Optional multi-location index for large/external assets:

```text
.project_os/indexes/asset_locations.tsv
```

Header:

```text
asset_id	location_id	role	path	storage_root	status	size_bytes	checksum	registered_at	last_checked_at	notes
```

Rules:

- Do not infer provenance from filenames alone.
- Mark unclear sources as `provenance_unknown` rather than guessing.
- Raw/reference assets are immutable by default.
- Derived outputs belong in run directories.
- If an asset has a large or external path, record the source and access rule; do not copy by default.
- Large files should be externalized by registry, not by duplicating them into `.project_os/`.
- Prefer a dry-run externalization report before moving/copying any large file.
- When multiple physical copies exist, keep `assets.tsv.path` as the primary/read path and record backup/mirror/archive locations in `asset_locations.tsv`.
- Do not use hard links for asset management. The harness must work across machines, mounts, filesystems, and platforms.
- Symlinks are not canonical state. If a local project uses symlinks for backward compatibility, they must be treated as optional convenience paths that can be rebuilt from `asset_id` + `asset_locations.tsv`.
- Use `register-asset` for durable asset registration and `add-run-input --asset-id <asset_id>` to link an asset to a run.
- Root `DATA_ASSETS.md` is refreshed only when absent or clearly harness-generated; if an existing root file is hand-authored, preserve it and write the generated view to `.project_os/exports/views/DATA_ASSETS.generated.md`.
- Canonical rows live in `.project_os/indexes/assets.tsv`; generated Markdown is a view, not source of truth.
- `.project_os/indexes/asset_usage.tsv` is refreshed from run manifests and records asset usage by branch/task/run/result.

Recommended status values:

```text
active, deprecated, replaced, unavailable, provenance_unknown
```

Core commands:

```bash
python scripts/project_os.py register-asset --root <project> --path <path> --kind data
python scripts/project_os.py add-run-input --root <project> --run-id <run_id> --asset-id <asset_id>
python scripts/project_os.py list-assets --root <project>
python scripts/project_os.py show-asset --root <project> --asset-id <asset_id>
python scripts/project_os.py checksum-asset --root <project> --asset-id <asset_id>
python scripts/project_os.py refresh-assets --root <project>
```

Planned externalization commands:

```bash
python scripts/project_os.py plan-externalize-assets --root <project> --threshold 500M --primary-root /media/teng/HP_P900 --backup-root /media/teng/备份盘2 --write-report
python scripts/project_os.py externalize-asset --root <project> --path <large-file> --primary-root /media/teng/HP_P900 --mode copy --apply --approved
python scripts/project_os.py adopt-external-asset --root <project> --path /absolute/already-external.faa --asset-id target_all_faa_chen2022_hmmer --old-path runs/.../inputs/target_all_faa.renamed_for_Chen2022_HMMER.faa --write-report
python scripts/project_os.py verify-external-assets --root <project>
python scripts/project_os.py list-asset-locations --root <project>
```

Safety rules for externalization:

- `plan-externalize-assets` is read-only/report-only.
- `externalize-asset` must be dry-run by default.
- `adopt-external-asset` must be dry-run by default.
- Copy/move updates require explicit `--apply --approved`.
- Registry-only adoption of an already external file also requires explicit `--apply --approved`.
- Hard-link based externalization is forbidden.
- Symlink creation, if ever supported for local backward compatibility, must be opt-in, non-canonical, and unnecessary for project recovery.
- Use checksum verification before registering a copied/moved location as available.
- Do not rewrite scripts, hand-authored root docs, or run manifests automatically; report old path -> new asset/location mappings for review.

Current implementation status:

- `list-asset-locations`
- `plan-externalize-assets`
- `externalize-asset`
- `adopt-external-asset`
- `verify-external-assets`

Current behavior notes:

- `externalize-asset` performs copy/move + checksum verify + asset/location registration + old-path mapping report.
- `adopt-external-asset` is for already external files; it registers canonical asset/location state in place, optional old-path/backup/mirror/archive mappings, and never copies or moves data.
- Hard links are forbidden.
- Symlinks are not created by these commands and are not canonical state.
- `verify-external-assets` is read-only and does not update `last_checked_at` automatically.
