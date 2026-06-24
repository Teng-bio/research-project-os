from __future__ import annotations

OS_DIR = '.project_os'
SCHEMA_VERSION = 1
HARNESS_VERSION = '0.1.0-p0'
DEFAULT_BRANCH = 'main'
ROOT_ENTRY_FILES = ['PROJECT_STATE.md', 'DATA_ASSETS.md', 'RESULTS_INDEX.md', 'RUNS_INDEX.tsv', 'DECISIONS.md']
SESSION_POINTERS = ['current_branch', 'current_task', 'current_run']

BRANCH_STATUSES = {'active', 'paused', 'completed', 'archived', 'abandoned'}
TASK_STATUSES = {'active', 'paused', 'blocked', 'completed', 'archived', 'superseded'}
RUN_STATUSES = {'active', 'completed', 'failed', 'pending_review', 'archived', 'superseded'}
RESULT_STATUSES = {'draft', 'candidate', 'accepted', 'current', 'superseded', 'legacy', 'release'}
RESULT_TYPES = {'figure', 'table', 'dataset', 'model', 'report', 'metric', 'text', 'artifact', 'package', 'other', 'file'}
ASSET_STATUSES = {'active', 'deprecated', 'replaced', 'unavailable', 'provenance_unknown'}
ASSET_LOCATION_ROLES = {'primary', 'backup', 'mirror', 'archive', 'cache', 'unavailable'}
ASSET_LOCATION_STATUSES = {'available', 'missing', 'stale_checksum', 'unchecked'}
RELEASE_STATUSES = {'draft', 'built', 'validated', 'released', 'archived'}
STAGES = {'Intake', 'Plan', 'Research', 'Run', 'Evaluate', 'Promote', 'Archive', 'Release'}

INDEX_HEADERS = {
    'branches.tsv': ['branch_id', 'status', 'parent_branch_id', 'title', 'branch_path', 'task_root', 'run_root', 'current_root', 'git_branch', 'created_at', 'closed_at', 'notes'],
    'tasks.tsv': ['task_id', 'branch_id', 'status', 'kind', 'stage', 'title', 'task_path', 'parent_task_id', 'created_at', 'updated_at', 'owner', 'priority', 'notes'],
    'runs.tsv': ['run_id', 'branch_id', 'task_id', 'status', 'result_status', 'run_path', 'created_at', 'closed_at', 'code_ref', 'notes'],
    'results.tsv': ['result_id', 'branch_id', 'task_id', 'run_id', 'status', 'type', 'path', 'title', 'created_at', 'accepted_at', 'promoted_to', 'replaced_by', 'notes'],
    'assets.tsv': ['asset_id', 'kind', 'path', 'version', 'source_url', 'source_note', 'immutable', 'status', 'registered_at', 'checksum', 'notes'],
    'asset_locations.tsv': ['asset_id', 'location_id', 'role', 'path', 'storage_root', 'status', 'size_bytes', 'checksum', 'registered_at', 'last_checked_at', 'notes'],
    'asset_usage.tsv': ['asset_id', 'branch_id', 'task_id', 'run_id', 'result_id', 'usage_kind', 'registered_at', 'notes'],
    'releases.tsv': ['release_id', 'status', 'path', 'created_at', 'source_branch_ids', 'source_result_ids', 'notes'],
}
ROOT_RUNS_HEADERS = INDEX_HEADERS['runs.tsv']
RUN_LINK_HEADERS = ['run_id', 'branch_id', 'status', 'path', 'created_at', 'notes']
RESULT_LINK_HEADERS = ['result_id', 'branch_id', 'status', 'path', 'run_id', 'created_at', 'notes']

BRANCH_REQUIRED_FIELDS = ['branch_id', 'title', 'status', 'branch_path', 'task_root', 'run_root', 'current_root', 'created_at', 'objective_file', 'context_file', 'handoff_file']
TASK_REQUIRED_FIELDS = ['task_id', 'title', 'status', 'kind', 'branch_id', 'created_at', 'updated_at', 'stage', 'task_path', 'objective_file', 'context_manifest']
RUN_REQUIRED_FIELDS = ['run_id', 'branch_id', 'task_id', 'status', 'created_at', 'code_ref', 'environment', 'inputs', 'parameters', 'commands', 'outputs', 'metrics', 'result_status']
PROJECT_REQUIRED_FIELDS = ['project_id', 'schema_version', 'profile', 'harness_version', 'created_at', 'default_branch']

WORKFLOW_TEXT = '''# Project OS Workflow

Default phases:

```text
Intake -> Plan -> Research -> Run -> Evaluate -> Promote -> Archive -> Release
```

Rules:

- Read `PROJECT_STATE.md` and this workflow before substantive work.
- Resolve continuation from `runtime/current_session` when set; otherwise use global `runtime/current_branch`, `runtime/current_task`, and `runtime/current_run`.
- A session focus lives under `.project_os/runtime/sessions/<session_id>/` and shadows global pointers only while `runtime/current_session` names that session.
- Load branch context from `.project_os/branches/<branch_id>/branch.json`, `objective.md`, and `context.md`.
- Load task context from `.project_os/branches/<branch_id>/tasks/<task_id>/context_manifest.jsonl`.
- Put generated formal run outputs under `runs/<branch_id>/<run_id>/` by default.
- Treat `.project_os/indexes/*.tsv` as canonical machine registries; root index docs are human-facing derived views.
- State-changing CLI operations use `.project_os/runtime/lock` as an advisory lock.
- Use `plan-recovery` for report-only crash/recovery inspection; it must not replay, roll back, delete tmp files, or remove locks.
- Register runs and results before promotion.
- Promote to `current/` or `release/` only after explicit user approval.
- Append lifecycle events to `.project_os/journals/events.jsonl` for state-changing CLI operations.
- Hooks are reserved but disabled by default; future hooks may observe events and call the CLI, but must not edit canonical state directly.
- Update `PROJECT_STATE.md`, branch handoff, or task `handoff.md` before stopping when project state changed.
'''

CONFIG_TEXT = '''schema_version: 1
project_os_dir: .project_os
# declarative: create-run uses the first root unless --run-root is provided; branch layer is always preserved.
run_roots:
  - runs
  - analysis_runs
human_entry_files:
  - PROJECT_STATE.md
  - DATA_ASSETS.md
  - RESULTS_INDEX.md
  - RUNS_INDEX.tsv
  - DECISIONS.md
# declarative but guarded: P0 still requires explicit dry-run/apply gates.
promotion_requires_user_approval: true
# declarative but portable: large assets are resolved by asset_id + asset_locations.tsv,
# never by hard-link semantics or platform-specific inode/device behavior.
external_assets:
  roots:
    - /media/teng/HP_P900
    - /media/teng/备份盘2
  default_primary_root: /media/teng/HP_P900
  default_backup_root: /media/teng/备份盘2
  default_mode: copy
  allow_optional_symlink_compat: false
# declarative: empty means use global runtime/current_* pointers.
runtime:
  current_session: ''
  session_pointer_names:
    - current_branch
    - current_task
    - current_run
# descriptive: install-adapters command arguments are authoritative.
adapters:
  codex: true
  claude: false
  opencode: false
# declarative, deferred: active hooks are not executed in P0/P1.
hooks:
  enabled: false
  mode: disabled
  dispatcher: none
  event_source: .project_os/journals/events.jsonl
  allowed_kinds:
    - session_summary
    - reminder
    - opt_in_maintenance
    - guard
  policy:
    must_call_cli: true
    cannot_write_canonical_state_directly: true
    failure_is_non_blocking_by_default: true
    guard_hooks_require_opt_in: true
'''

SPEC_TEXTS = {
    'project_rules.md': '# Project rules\n\nLink project-specific rules here. Keep canonical machine state in `.project_os/`.\n',
    'branch_model.md': '# Branch model\n\nEach branch/workstream has `.project_os/branches/<branch_id>/`, tasks under that directory, runs under `runs/<branch_id>/`, and branch current outputs under `current/branches/<branch_id>/`.\n',
    'task_tree.md': '# Task tree\n\nTasks are branch-local workspaces with globally unique task IDs. Future DAG dependencies live in `task.json.depends_on`.\n\nUse `update-task`, `update-task-stage`, `add-dependency`, `remove-dependency`, `add-context`, `remove-context`, `update-handoff`, and `close-task` for lifecycle/context updates.\n',
    'context_manifest.md': '# Context manifest policy\n\nBranch context is loaded from the runtime pointer chain. Task context should be loaded from `context_manifest.jsonl` instead of whole-repo guessing.\n',
    'session_runtime.md': '''# Session runtime policy

Default operation uses global runtime pointers:

```text
.project_os/runtime/current_branch
.project_os/runtime/current_task
.project_os/runtime/current_run
```

For parallel workstreams, named sessions may shadow those pointers:

```text
.project_os/runtime/current_session
.project_os/runtime/sessions/<session_id>/current_branch
.project_os/runtime/sessions/<session_id>/current_task
.project_os/runtime/sessions/<session_id>/current_run
.project_os/runtime/sessions/<session_id>/session.json
```

If `current_session` is empty, CLI commands use the global pointers. If it names a session, pointer reads/writes use that session directory. Session pointers must still reference existing branch/task/run objects and are checked by `validate` / `doctor`.

Session lifecycle states are `active`, `paused`, and `closed`.

- `pause-session` marks a session paused and clears it from `current_session` if it is active.
- `resume-session` marks a paused session active again; `--set-current` may also switch the runtime focus to it.
- `close-session` permanently closes a session and clears it if needed.
- `plan-session-cleanup` generates a dry-run/report-only candidate list for closed or paused sessions; it does not delete, move, or rewrite session directories.

Paused and closed sessions must not be used as the active `current_session`. Sessions are focus overlays only; they do not create branch/task/run/result identities and do not bypass promotion or release approval gates.

Session cleanup reports, when written, live under `.project_os/exports/session_cleanup/` and are generated inspection views only. Any future physical session archive/GC operation must remain explicit, reviewed, validation-gated, and non-canonical.
''',
    'run_provenance.md': '''# Run provenance policy

Every formal run should have `RUN_MANIFEST.json` with branch_id, task_id, inputs, parameters, code reference, environment, commands, outputs, metrics, and status.

Use CLI commands such as `add-run-input`, `add-run-command`, `add-run-output`, `add-run-metric`, `add-run-parameter`, and `capture-run-env` rather than hand-editing provenance when possible.

When package provenance is needed, run:

```bash
python scripts/project_os.py capture-run-env --root <project> --run-id <run_id> --pip-freeze --freeze-file docs/pip-freeze.txt
```

The freeze file is stored relative to the run directory by default and its project-relative path is recorded in `RUN_MANIFEST.json` under `environment.package_capture.freeze_file`.

Closing a run writes a human-readable `RUN_SUMMARY.md` with identity, counts, parameters, inputs, commands, outputs, metrics, promoted targets, environment, package sample, and notes. `RUN_MANIFEST.json` remains the source of truth.
''',
    'result_curation.md': '''# Result curation policy

Results move from draft to candidate to accepted/current only through explicit review and registration. Promotion truth is `results.tsv` plus `current/`.

Current result views are derived:

- Branch current targets live under `current/branches/<branch_id>/`.
- Project current targets live under `current/project/`.
- `show-current --scope branch|project|all --audit` may be used to inspect current targets and promotion warnings.
- Do not edit `current/` directly as canonical provenance; update or promote results through the CLI so `results.tsv` and events stay authoritative.

Use `accept-result --approved` before release inclusion when a result is accepted but not promoted. Use `promote-result --apply --approved` only after reviewing the dry-run target under `current/`. Use `supersede-result --approved` to preserve replacement provenance instead of deleting older outputs.
''',
    'data_assets.md': '# Data assets policy\n\nUse `.project_os/indexes/assets.tsv` as canonical and the generated asset Markdown as a human view. Root `DATA_ASSETS.md` is refreshed only when absent or already harness-generated; if it is hand-authored, preserve it and write `.project_os/exports/views/DATA_ASSETS.generated.md` instead. Do not infer provenance from filenames alone.\n\nRun inputs may reference registered assets by `asset_id`; `.project_os/indexes/asset_usage.tsv` is the asset -> run/result impact view.\n\nLarge files should be externalized by registry and location metadata, not by copying them into `.project_os/`.\n\nUse `.project_os/indexes/asset_locations.tsv` for multi-location primary/backup/mirror/archive metadata.\n\nDefault external storage roots may be declared in `.project_os/config.yaml` under `external_assets.roots`, but canonical recovery still resolves through `asset_id` + `asset_locations.tsv`.\n\nImplemented externalization/report commands: `plan-externalize-assets`, `externalize-asset`, `adopt-external-asset`, `verify-external-assets`, and `list-asset-locations`.\n\nUse `adopt-external-asset` when the file already lives outside the project root and should be registered in place without copy/move.\n\nDo not use hard links for asset management. The harness must work across machines, mount points, filesystems, and platforms.\n\nSymlinks are not canonical state. If a local project keeps symlinks for backward compatibility with old scripts, they must remain optional convenience paths that can be rebuilt from `asset_id` plus `.project_os/indexes/asset_locations.tsv`.\n',
    'event_journal.md': '# Event journal policy\n\nState-changing CLI commands append compact JSON events to `.project_os/journals/events.jsonl`.\n\nThis journal is the stable event source for manual hook reports, dashboards, repair tooling, audit summaries, and future opt-in automation. Active automatic hooks are deferred and disabled by default. Current manual hook reports may read this journal and suggest `project_os.py` commands, but they do not execute those commands or edit canonical state directly. Future hooks may observe this journal and call `project_os.py`, but they must not edit canonical state directly.\n\nIf `events.jsonl` is missing, use `project_os.py restore-journal` as a dry-run first, then `--apply --approved` only after review. This command creates the missing journal and appends `journal.restored`; it does not overwrite an existing journal or reconstruct historical lifecycle events.\n\n`project_os.py plan-recovery --write-report` writes only a generated inspection report and does not append lifecycle events, because recovery reports must not mutate canonical state.\n',
    'hooks.md': '# Hooks policy\n\nHooks are optional automation/reporting helpers and are disabled by default for automatic execution.\n\nCurrent project contract:\n\n- `.project_os/journals/events.jsonl` is the stable event source for manual hook reports and future hooks.\n- The core harness must work without hooks.\n- Manual hook reports may be generated with `project_os.py list-hooks` and `project_os.py dispatch-hooks`.\n- Hook reports may suggest `project_os.py` commands, but current manual dispatch does not execute them.\n- Future active hooks may observe events and call `project_os.py`.\n- Hooks must not edit canonical state files directly.\n- Guard hooks for promotion, release, archive, or destructive maintenance must be explicit opt-in.\n\nDefault reserved configuration lives in `.project_os/config.yaml` under `hooks:`.\n\nGenerated hook reports, when requested, live under `.project_os/exports/hooks/` and are derived views only.\n',
    'integrity_rules.md': '''# Integrity rules

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
''',
    'user_profile.md': '# User profile policy\n\nCustomize this file for the project. Keep canonical facts in root human entry files and `.project_os/` indexes.\n',
    'release_packaging.md': '# Release packaging policy\n\nRelease packages should be built from explicit accepted/current result IDs.\n\nDefault package layout:\n\n```text\nrelease/<release_id>/\n  README.md\n  MANIFEST.tsv\n  CHECKSUMS.tsv\n  artifacts/\n```\n\nUse `build-release` as dry-run first, then `--apply --approved` only after the selected results are confirmed.\n',
}

ROOT_DOC_DEFAULTS = {
    'PROJECT_STATE.md': '# PROJECT_STATE\n\n## Project Summary\n\nTBD.\n\n## Current Goal\n\nTBD.\n\n## Current Status\n\n- Branch-first research-project-os harness initialized; project-specific status still needs review.\n\n## Key Paths\n\n- `.project_os/`\n- `.project_os/branches/main/`\n- `runs/main/`\n- `current/branches/main/`\n\n## Decisions\n\n- Use `.project_os/indexes/*.tsv` as canonical machine registries.\n\n## Recent Changes\n\n- Initialized research-project-os harness.\n\n## Open Problems\n\n- Fill in project-specific state.\n\n## Next Step\n\n- Review project state and create the first active task.\n\n## Resume Prompt\n\nContinue by reading `PROJECT_STATE.md`, `.project_os/workflow.md`, and runtime pointers.\n',
    'DATA_ASSETS.md': '# DATA_ASSETS\n\nHuman-facing data/source view generated from `.project_os/indexes/assets.tsv`.\n\nNo registered assets yet.\n\n## Policy\n\n- Canonical rows live in `.project_os/indexes/assets.tsv`.\n- Multi-location rows live in `.project_os/indexes/asset_locations.tsv`.\n- Usage links live in `.project_os/indexes/asset_usage.tsv`.\n- Do not infer provenance from filenames alone.\n',
    'RESULTS_INDEX.md': '# RESULTS_INDEX\n\nHuman-facing index generated from `.project_os/indexes/results.tsv`.\n',
    'RUNS_INDEX.tsv': '\t'.join(ROOT_RUNS_HEADERS) + '\n',
    'DECISIONS.md': '# DECISIONS\n\nDurable project decisions.\n',
}

PROJECT_OS_BLOCK_START = '<!-- PROJECT_OS:START -->'
PROJECT_OS_BLOCK_END = '<!-- PROJECT_OS:END -->'

PROJECT_OS_AGENTS_BLOCK = f'''{PROJECT_OS_BLOCK_START}
## research-project-os

This file is an agent adapter. It points Codex/Claude/other agents at the
project-local workflow harness under `.project_os/`. It is not the canonical
project database.

### Authority order

When instructions conflict, follow this order:

1. User's current explicit instruction.
2. This `AGENTS.md` file.
3. `PROJECT_STATE.md` and `.project_os/` runtime pointers.
4. Active branch/task context from `.project_os/branches/<branch_id>/...`.
5. Files listed in the active task `context_manifest.jsonl`.
6. General coding/research skills as helpers only.

Do not create a parallel state system such as `task_plan.md`,
`PROJECT_STATUS.md`, ad-hoc `current_plan.md`, or duplicate run folders unless
the user explicitly asks to replace the harness workflow.

### Startup workflow

Before substantive work:

1. Confirm the repository root.
2. Read `PROJECT_STATE.md`.
3. Read `.project_os/workflow.md`.
4. Resolve runtime focus:
   - `.project_os/runtime/current_session`
   - `.project_os/runtime/current_branch`
   - `.project_os/runtime/current_task`
   - `.project_os/runtime/current_run`
5. If `current_session` is set, use that session's pointers under
   `.project_os/runtime/sessions/<session_id>/`.
6. Load branch context from `.project_os/branches/<branch_id>/branch.json`,
   `objective.md`, and `context.md`.
7. If a current task exists, load only the files listed in
   `.project_os/branches/<branch_id>/tasks/<task_id>/context_manifest.jsonl`.
8. Use the `research-project-os` skill and its `project_os.py` backend for
   deterministic state changes.

### Harness rules

- Canonical machine state lives in `.project_os/project.json`,
  `.project_os/indexes/*.tsv`, `.project_os/journals/events.jsonl`, runtime
  pointers, and branch/task/run/result/release manifests.
- Root files such as `PROJECT_STATE.md`, `DATA_ASSETS.md`, `RUNS_INDEX.tsv`,
  `RESULTS_INDEX.md`, and `DECISIONS.md` are human entry points.
- Create/register a run before formal analysis, training, evaluation,
  benchmarking, or artifact generation.
- Register useful outputs as candidate results before promotion.
- Never promote to `current/` or build/write `release/` without explicit user
  approval and the required approval flags.
- Large assets must resolve through `asset_id` plus
  `.project_os/indexes/asset_locations.tsv`; do not rely on hard links, inode
  identity, device numbers, mount layout, or symlinks as canonical state.
- Update `PROJECT_STATE.md` or task handoff files before stopping when project
  state changed.
- Do not delete, quarantine, move historical runs, or rewrite generated result
  history without a dry-run plan and explicit user approval.

### Project-specific overlay

Each project should adjust only the local overlay details:

- project root and theme;
- default environment / interpreter / preflight command;
- authoritative design or method documents;
- domain-specific source, data, run, model, and report directories;
- project-specific validation or smoke-test commands.

Useful trigger phrases: `项目骨架`, `新项目骨架`, `搭项目骨架`, `项目工作流骨架`, `开工`, `继续项目`, `新建分支`, `开始运行`, `记录结果`, `当前结果`, `设为当前结果`.
{PROJECT_OS_BLOCK_END}
'''

CLAUDE_BLOCK = f'''{PROJECT_OS_BLOCK_START}
## research-project-os

This project uses `.project_os/` as the canonical workflow harness.

Claude should resume work by reading `PROJECT_STATE.md`, `.project_os/workflow.md`, runtime pointers, branch context, and the active task context manifest. Do not duplicate project state into `CLAUDE.md`; use the `project_os.py` CLI for deterministic operations. Active hooks are intentionally not required.
{PROJECT_OS_BLOCK_END}
'''

REPO_PROJECT_SKELETON_SKILL = '''---
name: project-skeleton
description: Repository-local entry for this project's `.project_os/` workflow. Use when the user says 项目骨架, 新项目骨架, 搭项目骨架, 项目工作流骨架, 开工, 继续项目, or asks to resume this project.
---

# project-skeleton

This repository uses `.project_os/` as the project workflow source of truth.

1. Read `PROJECT_STATE.md`.
2. Read `.project_os/workflow.md`.
3. Resolve `.project_os/runtime/current_branch`, `current_task`, and `current_run`.
4. Load branch context, then active task `context_manifest.jsonl`.
5. Use the global `research-project-os` skill and its `project_os.py` backend for deterministic operations.
'''
