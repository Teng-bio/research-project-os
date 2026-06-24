# AGENTS.md — research-project-os

This repository documents and packages the general `.project_os/` harness for long-running projects.

## Rules

- Treat the harness as domain-neutral infrastructure, not as a TypeII PKS-specific workflow.
- Keep examples clearly labeled as examples; do not hard-code project-specific paths into reusable docs or templates.
- Preserve the no-hardlink external asset policy: portable references are `asset_id + asset_locations.tsv`.
- Promotion, release building, and journal restoration that write state must require explicit approval gates.
- Prefer report-only planners before destructive or large filesystem operations.
- Do not commit secrets, `.env`, credentials, private keys, cache directories, or large generated project assets.
- Validate Python changes with:
  - `python3 -m py_compile harness/research-project-os/scripts/*.py`
  - `python3 harness/research-project-os/scripts/smoke_project_os_e2e.py`

## Documentation style

- README explains purpose and quick start.
- `docs/ARCHITECTURE.md` explains the model and lifecycle.
- `docs/ASSETS.md` explains external asset portability.
- `docs/AGENT_INTEGRATION.md` explains how Codex/Claude/other agents should use the harness.
