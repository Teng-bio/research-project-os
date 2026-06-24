# Data assets policy

Use `.project_os/indexes/assets.tsv` as canonical and the generated asset Markdown as a human view. Root `DATA_ASSETS.md` is refreshed only when absent or already harness-generated; if it is hand-authored, preserve it and write `.project_os/exports/views/DATA_ASSETS.generated.md` instead. Do not infer provenance from filenames alone.

Run inputs may reference registered assets by `asset_id`; `.project_os/indexes/asset_usage.tsv` is the asset -> run/result impact view.

Large files should be externalized by registry and location metadata, not by copying them into `.project_os/`.

Use `.project_os/indexes/asset_locations.tsv` for multi-location primary/backup/mirror/archive metadata.

Default external storage roots may be declared in `.project_os/config.yaml` under `external_assets.roots`, but canonical recovery still resolves through `asset_id` + `asset_locations.tsv`.

Use `adopt-external-asset` when the file already lives outside the project root and should be registered in place without copy/move. Use `externalize-asset` only when an in-project file needs copy/move plus registry updates.

Do not use hard links for asset management. The harness must work across machines, mount points, filesystems, and platforms.

Symlinks are not canonical state. If a local project keeps symlinks for backward compatibility with old scripts, they must remain optional convenience paths that can be rebuilt from `asset_id` plus `.project_os/indexes/asset_locations.tsv`.
