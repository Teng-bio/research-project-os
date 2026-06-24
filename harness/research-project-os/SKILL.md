---
name: research-project-os
description: General repository-local research/project harness under `.project_os/` and first router for long-running, multi-step projects across domains. Use for research-project-os, project harness, 项目骨架, 通用项目工作台, 开工, 继续项目, 继续当前任务, 继续下一步, 大项目, 长期项目, 逐步推进, 当前进展, 恢复上下文, 制定计划, 拆解任务, plan out, break down, organize multi-step work, task_plan.md, findings.md, progress.md, 开始分析, 先跑, 先画, 绘图, 画图, 生成结果, 开始运行, 记录结果, 当前结果, run provenance, RESULTS_INDEX, DATA_ASSETS, current_task, result promotion, release workflow, 外置数据, 恢复检查. In any `.project_os/` project, also use before domain commands such as 系统发育, 发育树, 进化树, Newick, FASTA比对, PHYLIP, Nexus, alignment/tree/parsimony/treeness/RCV, ortholog, 同源基因, 分子进化, bootstrap, model training, 深度学习, R绘图, Python分析, and before 项目状态/写一个项目状态文档/更新项目状态文档/总结项目状态/记录当前项目进度/项目文档太大/拆分项目文档; establishes branch/task/run/result/assets first.
---

# research-project-os

Use this skill to operate a **project-local harness**, not to create a second scientific plan.

## Project harness precedence

If the current directory, project root, or a parent directory contains `.project_os/`, this skill is the **primary controller** for the turn. Route first through `project_os.py start`, `status`, or `route`; then execute the domain work from the active branch/task/run context and record inputs, commands, outputs, results, and assets in the harness.

Absorbed conflict-trigger coverage:

- Former planning triggers (`大项目`, `逐步推进`, `继续下一步`, `制定计划`, `拆解任务`, `当前进展`, `恢复上下文`, `plan out`, `break down`, `organize multi-step work`, `5+ tool calls`, `task_plan.md`, `findings.md`, `progress.md`, `/clear` recovery) become `.project_os` task/branch/session routing when a harness exists.
- Former project-state triggers (`项目状态`, `写一个项目状态文档`, `更新项目状态文档`, `总结项目状态`, `记录当前项目进度`, `整理项目当前进展`, `项目文档太大`, `拆分项目文档`, handoff/resume/adopt project) become `status`, `summarize-state`, handoff, and derived index updates in `.project_os`.
- Former phylogeny triggers (`系统发育`, `发育树`, `进化树`, `Newick`, `FASTA比对`, `PHYLIP`, `Nexus`, `alignment`, `tree`, `parsimony`, `treeness`, `RCV`, `DVMC`, `ortholog`, `同源基因`, `分子进化`, `bootstrap`, taxa/group comparison) must enter through the harness first; do not let a standalone specialist create a parallel state system.

Core split:

```text
.project_os/                 # agent harness, runtime pointers, canonical branch/task/run/result indexes
PROJECT_STATE.md             # thin human handoff
DATA_ASSETS.md               # human data/source view; protected if hand-authored
RUNS_INDEX.tsv               # generated human run view
RESULTS_INDEX.md             # generated accepted/candidate/current result entry point
DECISIONS.md                 # durable decisions
```

## Startup

1. Detect the project root.
2. Read `PROJECT_STATE.md` when present.
3. If `.project_os/` exists, read:
   - `.project_os/workflow.md`
   - `.project_os/runtime/current_session`, `current_branch`, `current_task`, and `current_run`
   - when `current_session` is set, `.project_os/runtime/sessions/<session_id>/current_branch`, `current_task`, and `current_run`
   - `.project_os/branches/<branch_id>/branch.json`, `objective.md`, and `context.md`
   - the active task `context_manifest.jsonl`
4. Load branch context first, then only files listed in the task context manifest unless the user asks for broader inventory.
5. Use `scripts/project_os.py` for deterministic operations.


## Short trigger router

For compact phrases such as `开工`, `项目骨架`, `新建分支`, `新建会话`, `切会话`, `会话清理`, `开始运行`, `记录结果`, `当前结果`, or `设为当前结果`, route through `references/short_trigger_router.md`:

```text
short phrase -> intent -> state check -> CLI action -> verification
```

Do not edit harness files directly from a trigger phrase. Use `project_os.py` and preserve dry-run / approval gates.

For an explicit machine-readable route plan without changing files:

```bash
python scripts/project_os.py route --root <project> "开工"
python scripts/project_os.py route --root <project> "新建任务" --title "..."
python scripts/project_os.py route --root <project> "记录结果" --path <path>
python scripts/project_os.py route --root <project> "当前结果"
python scripts/project_os.py route --root <project> "捕获运行环境" --run-id <run_id> --pip-freeze
python scripts/project_os.py route --root <project> "新建会话" --session-id <session_id> --branch-id <branch_id> --set-current
python scripts/project_os.py route --root <project> "恢复检查" --write-report
python scripts/project_os.py route --root <project> "恢复事件日志"
python scripts/project_os.py route --root <project> "hook报告" --event run.closed --kind reminder --limit 3
```

`当前结果` / `查看当前结果` are read-only inspection triggers: they route to `show-current --audit` and must not be treated as `设为当前结果`.

For promotion/release trigger plans, `--apply` must be paired with explicit `--approved`; otherwise the router should report the approval as missing and keep the plan non-ready.

## Core commands

From this skill directory:

```bash
python scripts/project_os.py new-project --root <project> --title "..." --profile research --platforms codex --apply
python scripts/project_os.py init --root <project> --apply
python scripts/project_os.py start --root <project>
python scripts/project_os.py status --root <project>
python scripts/project_os.py route --root <project> "开工"
python scripts/project_os.py doctor --root <project>
python scripts/project_os.py doctor --root <project> --repair-plan
python scripts/project_os.py install-adapters --root <project> --platforms codex claude --apply
python scripts/project_os.py validate --root <project>
python scripts/smoke_project_os_e2e.py
python scripts/project_os.py create-branch --root <project> --branch-id method_a --title "Method A" --set-current
python scripts/project_os.py list-branches --root <project>
python scripts/project_os.py create-session --root <project> --session-id paper_a --branch-id method_a --set-current
python scripts/project_os.py set-current-session --root <project> --session-id paper_a
python scripts/project_os.py set-current-session --root <project> --clear
python scripts/project_os.py list-sessions --root <project>
python scripts/project_os.py pause-session --root <project> --session-id paper_a
python scripts/project_os.py resume-session --root <project> --session-id paper_a --set-current
python scripts/project_os.py plan-session-cleanup --root <project> --status closed --write-report
python scripts/project_os.py plan-recovery --root <project>
python scripts/project_os.py plan-recovery --root <project> --write-report
python scripts/project_os.py create-task --root <project> --title "..." --kind analysis --set-current
python scripts/project_os.py update-task --root <project> --task-id <task_id> --owner <name> --priority high
python scripts/project_os.py update-task-stage --root <project> --task-id <task_id> --stage Run
python scripts/project_os.py add-dependency --root <project> --task-id <task_id> --depends-on-task <upstream_task_id>
python scripts/project_os.py add-context --root <project> --task-id <task_id> --path <path> --purpose "..."
python scripts/project_os.py create-run --root <project> --task-id <task_id> --slug "..."
python scripts/project_os.py update-run --root <project> --run-id <run_id> --status completed
python scripts/project_os.py list-runs --root <project> --branch-id <branch_id>
python scripts/project_os.py add-run-input --root <project> --run-id <run_id> --asset-id <asset_id>
python scripts/project_os.py add-run-command --root <project> --run-id <run_id> --command "..."
python scripts/project_os.py add-run-output --root <project> --run-id <run_id> --path <path>
python scripts/project_os.py add-run-metric --root <project> --run-id <run_id> --name <name> --value <json-or-text>
python scripts/project_os.py add-run-parameter --root <project> --run-id <run_id> --param alpha=0.1
python scripts/project_os.py capture-run-env --root <project> --run-id <run_id> --pip-freeze --freeze-file docs/pip-freeze.txt
python scripts/project_os.py close-run --root <project> --run-id <run_id> --status completed
python scripts/project_os.py register-result --root <project> --run-id <run_id> --path <path> --status candidate --type artifact
python scripts/project_os.py accept-result --root <project> --result-id <result_id> --approved
python scripts/project_os.py promote-result --root <project> --result-id <result_id> --to current/branches/<branch_id>/<file> --apply --approved
python scripts/project_os.py show-current --root <project> --branch-id <branch_id>
python scripts/project_os.py register-asset --root <project> --path <path> --kind data
python scripts/project_os.py list-assets --root <project>
python scripts/project_os.py list-asset-locations --root <project>
python scripts/project_os.py plan-externalize-assets --root <project> --threshold 500M --write-report
python scripts/project_os.py externalize-asset --root <project> --path <large-file> --primary-root /media/teng/HP_P900
python scripts/project_os.py adopt-external-asset --root <project> --path /absolute/already-external.faa --asset-id <asset_id> --old-path runs/.../inputs/legacy.faa --write-report
python scripts/project_os.py verify-external-assets --root <project> --checksum
python scripts/project_os.py record-decision --root <project> --title "..." --body "..."
python scripts/project_os.py update-handoff --root <project> --scope task --message "..."
python scripts/project_os.py summarize-state --root <project>
python scripts/project_os.py export-dashboard --root <project> --apply --sqlite
python scripts/project_os.py list-hooks --root <project>
python scripts/project_os.py dispatch-hooks --root <project> --limit 1
python scripts/project_os.py build-release --root <project> --release-id <release_id> --result-id <result_id> --apply --approved
python scripts/project_os.py validate-release --root <project> --release-id <release_id>
python scripts/project_os.py migrate-branch-first --root <project>
python scripts/project_os.py migrate-branch-first --root <project> --apply --mode copy
python scripts/project_os.py restore-journal --root <project>
python scripts/project_os.py restore-journal --root <project> --apply --approved
python scripts/project_os.py refresh-indexes --root <project>
```

Use `new-project` or `init` without `--apply` first when adopting an unfamiliar project.

For harness development or release validation, run the disposable end-to-end
smoke script from this skill directory:

```bash
python scripts/smoke_project_os_e2e.py
```

It creates temporary projects, uses explicit temporary external asset roots,
checks approval gates, and expects final `validate` to report `0 errors / 0
warnings` in the main fixture. Use `--keep` only when you need to inspect the
generated temporary fixtures.

## Project skeleton entry

When triggered by `项目骨架`, `新项目骨架`, or `搭项目骨架`:

- If `.project_os/` is absent, run `new-project` as a dry-run first and ask before applying unless the user clearly requested changes.
- If `.project_os/` exists, run `start` and resume from the active task/run.
- Treat `project_os.py` as the deterministic backend; users do not need to remember Python commands.

## Operating rules

- Treat `.project_os/` as the agent workspace and runtime source of truth.
- Treat branch/workstream as a physical workspace under `.project_os/branches/<branch_id>/`.
- Treat `.project_os/indexes/*.tsv`, `.project_os/project.json`, and `.project_os/journals/events.jsonl` as canonical machine state; if the journal file is missing, use `restore-journal` dry-run then reviewed `--apply --approved` rather than hand-editing or reinitializing blindly.
- Treat root Markdown/TSV files as human-readable derived/handoff entry points.
- Do not overwrite a hand-authored root `DATA_ASSETS.md`; when it is not a harness-generated view, write the generated asset view to `.project_os/exports/views/DATA_ASSETS.generated.md`.
- Treat `.project_os/runtime/current_session` as optional focus routing: when empty, commands use global runtime pointers; when set, commands read/write that session's `current_branch` / `current_task` / `current_run`.
- Treat `status` as a read-only operational snapshot: it reports session-aware runtime focus, counts, active/last run summary, and candidate/current result audit summary, but it must not refresh indexes, append events, promote results, repair `current/`, or rewrite result indexes.
- Treat `summarize-state` as a read-only handoff/status payload: it reports session-aware runtime focus plus derived current-result/audit summary, but it must not promote results, repair `current/`, or rewrite result indexes.
- Treat `plan-session-cleanup` as a generated report-only session archive/GC planner; it must not delete, move, or rewrite session directories.
- Default formal run layout is `runs/<branch_id>/<run_id>/`.
- State-changing CLI operations use an advisory lock at `.project_os/runtime/lock`.
- Treat `plan-recovery` as a generated report-only crash/recovery inspection planner; it may report stale locks, tmp files, malformed journal lines, missing paths, pointer drift, index drift, and stale generated views, but must not replay, roll back, delete tmp files, remove locks, or rewrite canonical state.
- Hooks are disabled by default for automatic execution. `list-hooks` / `dispatch-hooks` can produce manual report-only summaries and suggested CLI commands from `events.jsonl`; they must not edit canonical state directly or bypass approval gates.
- Runs are provenance, not the place humans should search manually for final results.
- Large asset recovery must resolve through `asset_id` + `.project_os/indexes/asset_locations.tsv`, not hard links or symlink assumptions.
- For already external files, prefer `adopt-external-asset` over `externalize-asset`; adoption is registry-only and must not copy/move data.
- Promotion to `current/`, release apply, or `restore-journal --apply` requires explicit user approval via `--approved`; dry-run planning remains available without it.
- Dashboard/export files are generated inspection views only; graph nodes/edges, current-result/promotion-audit views, session views, cleanup candidates, hooks status/config views, and recovery summaries in JSON/HTML/SQLite are derived from canonical state and must not become editable state.
- Do not invent or replace domain plans. Link existing authoritative plans from task context manifests.
- Do not move, delete, quarantine, or rewrite historical runs without a dry-run plan and user approval.
- Keep `PROJECT_STATE.md` thin; put task/run/result detail in `.project_os/` indexes and task folders.

## References

Read only what the current task needs:

- `references/short_trigger_router.md` for short Chinese/English trigger routing to harness intents.
- `references/harness_contract.md` for the file contract.
- `references/workflow_phases.md` for Intake→Release phases.
- `references/project_adoption.md` for adding `.project_os/` to an existing project.
- `references/branch_schema.md`, `context_manifest_schema.md`, `task_schema.md`, `run_manifest_schema.md`, `result_index_schema.md`, and `data_asset_schema.md` for schemas.
- `references/lifecycle_events.md` for event names backed by `.project_os/journals/events.jsonl`.
- `references/hooks_contract.md` for the deferred hooks interface, default-disabled policy, and future dispatcher/handler contract.
- `references/integrity_rules.md` for doctor/validate rules, dependency DAG checks, derived-view drift, and repair-plan policy.
- `references/adapter_policy.md` for Codex/Claude/OpenCode boundary rules.
- `references/safety_and_boundaries.md` for non-destructive operation rules.
