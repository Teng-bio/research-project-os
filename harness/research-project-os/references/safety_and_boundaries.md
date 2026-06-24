# Safety and boundaries

## Non-destructive by default

- Inventory before cleanup.
- Dry-run before reorganization.
- No deletion, quarantine, or overwrite of historical runs without explicit user approval.
- No automatic promotion to accepted/current.

## Existing plan boundary

If a project already has an authoritative plan, the harness links to it. The harness must not create a second method route, replace current scientific assumptions, or change execution order.

## Validation boundary

Put validation at fixed boundaries:

- project adoption/init;
- task creation;
- run creation;
- context manifest loading;
- result registration;
- promotion/release packaging.

Inside project-specific analysis code, do not scatter generic fallback logic just because the harness exists.

## Profile boundary

Long-term user preferences may be recorded only when useful and reviewable. Do not store sensitive credentials or private access material in `.project_os/`.
