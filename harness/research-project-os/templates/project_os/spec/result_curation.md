# Result curation policy

Results move from draft to candidate to accepted/current only through explicit review and registration. Promotion truth is `results.tsv` plus `current/`.

Current result views are derived:

- Branch current targets live under `current/branches/<branch_id>/`.
- Project current targets live under `current/project/`.
- `show-current --scope branch|project|all --audit` may be used to inspect current targets and promotion warnings.
- Do not edit `current/` directly as canonical provenance; update or promote results through the CLI so `results.tsv` and events stay authoritative.

Use `accept-result --approved` before release inclusion when a result is accepted but not promoted. Use `promote-result --apply --approved` only after reviewing the dry-run target under `current/`. Use `supersede-result --approved` to preserve replacement provenance instead of deleting older outputs.
