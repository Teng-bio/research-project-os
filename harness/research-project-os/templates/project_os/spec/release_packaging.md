# Release packaging policy

Release packages should be built from explicit accepted/current result IDs.

Default package layout:

```text
release/<release_id>/
  README.md
  MANIFEST.tsv
  CHECKSUMS.tsv
  artifacts/
```

Use `build-release` as dry-run first, then `--apply --approved` only after the selected results are confirmed.
