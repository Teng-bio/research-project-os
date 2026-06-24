# Integrity rules

`doctor` and `validate` check branch/task/run/result/asset/release consistency, dependency DAGs, derived human view drift, event references, and journal/current-snapshot coverage.

Journal snapshot audit:

- Events that name branch/task/run/result/asset/release IDs should still resolve to current canonical rows.
- Non-legacy canonical rows should have lifecycle event coverage.
- Rows predating a `project.adopted` event may be treated as adopted legacy state.
- Missing event coverage is a warning that requires provenance review, not automatic event rewriting.

Use `doctor --repair-plan` for non-executing repair suggestions. Destructive or provenance-changing repairs still require explicit user approval.

Recovery inspection:

- `plan-recovery` is report-only.
- It may report stale advisory locks, tmp leftovers, malformed journal lines, missing paths, pointer drift, manifest/index drift, and stale generated views.
- It must not replay journals, roll back operations, delete tmp files, remove locks, repair pointers, or rewrite canonical state.
