# Short Trigger Router

This document defines the short natural-language trigger layer for `research-project-os`.

The router maps compact user phrases to harness intents, then to deterministic `project_os.py` commands. It exists so users do not need to remember CLI commands, while the harness still keeps all state changes in the backend.

The deterministic backend exposes this layer as a **planning command**:

```bash
python scripts/project_os.py route --root <project> "开工"
python scripts/project_os.py route --root <project> "新建分支" --title "Method A" --branch-id method_a --set-current
python scripts/project_os.py route --root <project> "记录结果" --path outputs/result.txt
python scripts/project_os.py route --root <project> "当前结果"
python scripts/project_os.py route --root <project> "设为当前结果" --result-id <result_id> --to current/branches/<branch_id>/<file>
python scripts/project_os.py route --root <project> "捕获运行环境" --run-id <run_id> --pip-freeze --freeze-file docs/pip-freeze.txt
python scripts/project_os.py route --root <project> "新建会话" --session-id paper_a --branch-id paper_a --set-current
python scripts/project_os.py route --root <project> "暂停会话" --session-id paper_a
python scripts/project_os.py route --root <project> "恢复会话" --session-id paper_a --set-current
python scripts/project_os.py route --root <project> "会话清理" --status closed --write-report
python scripts/project_os.py route --root <project> "恢复检查" --write-report
python scripts/project_os.py route --root <project> "恢复事件日志"
python scripts/project_os.py route --root <project> "hook状态"
python scripts/project_os.py route --root <project> "hook报告" --kind reminder
python scripts/project_os.py route --root <project> "hook报告" --event run.closed --kind reminder --limit 3
python scripts/project_os.py route --root <project> "hook报告" --event-index 5 --write-report
python scripts/project_os.py route --root <project> "规划外置数据" --threshold 500M --primary-root /media/teng/HP_P900 --backup-root /media/teng/备份盘2 --write-report
python scripts/project_os.py route --root <project> "外置数据" --path data/huge.faa --primary-root /media/teng/HP_P900 --mode copy
python scripts/project_os.py route --root <project> "纳管外置数据" --path /media/teng/HP_P900/data/huge.faa --asset-id huge_faa --old-path runs/.../inputs/huge.faa --write-report
python scripts/project_os.py route --root <project> "验证外置数据" --asset-id <asset_id> --audit
python scripts/project_os.py route --root <project> "大项目逐步推进"
python scripts/project_os.py route --root <project> "task_plan.md"
python scripts/project_os.py route --root <project> "先画一个无产物标注的发育树吧"
```

`explain-trigger` is an alias for `route`. Both commands **only produce a route plan**; they do not execute the planned commands or edit project files.

## Design rule

```text
short phrase -> intent -> state check -> CLI action -> verification
```

The short trigger layer must not directly edit project files. It routes to `project_os.py` and follows the same dry-run / approval rules as the full skill.

## Router layers

| Layer | Responsibility | Example |
|---|---|---|
| Phrase layer | Recognize short Chinese/English user phrases | `开工`, `新建分支`, `记结果` |
| Intent layer | Normalize phrase to harness intent | `resume_project`, `create_branch`, `register_result` |
| State layer | Inspect `.project_os/` and runtime pointers | current branch/task/run |
| Action layer | Choose CLI command or ask for missing required input | `project_os.py start`, `create-run` |
| Verification layer | Confirm expected files/indexes/pointers changed | `doctor`, `status`, `refresh-indexes` |

The route plan JSON includes:

- `intent` and `group`
- current harness `state`
- `missing` required fields, if any
- `safety_gates`
- `planned_commands`
- `verification_commands`
- `ready`

## Intent groups

### 1. Bootstrap / resume

| User phrase | Intent | State check | Default action |
|---|---|---|---|
| `项目骨架` | auto bootstrap/resume | Does `.project_os/` exist? | Missing: dry-run `new-project`; existing: `start` |
| `新项目骨架` | bootstrap_project | Does `.project_os/` exist? | dry-run `new-project` unless user explicitly says apply |
| `搭项目骨架` | bootstrap_project | Does `.project_os/` exist? | dry-run `new-project` |
| `初始化项目骨架` | bootstrap_project | Does `.project_os/` exist? | dry-run `new-project` |
| `开工` | resume_project | Read runtime pointers | `start` |
| `继续项目` | resume_project | Read runtime pointers | `start` |
| `继续当前任务` | resume_project | Read current branch/task/run | `start`, then load context manifest |
| `继续下一步` | resume_project | Read current branch/task/run | `start`, then decide next task/run from harness state |
| `大项目` / `逐步推进` / `大项目逐步推进` | resume_project | Read or bootstrap harness state | Existing: `start`; missing harness: dry-run `new-project` |
| `恢复上下文` | resume_project | Read runtime pointers and context manifest | `start` |
| `看项目状态` | show_status | `.project_os/` exists? | `status` |
| `当前进展` | show_status | `.project_os/` exists? | `status` |
| `检查项目骨架` | doctor_project | `.project_os/` exists? | `doctor` |
| `修复计划` | repair_plan | `.project_os/` exists? | `doctor --repair-plan` |
| `怎么修` | repair_plan | `.project_os/` exists? | `doctor --repair-plan` |
| `恢复计划` | plan_recovery | `.project_os/` exists? | report-only `plan-recovery` |
| `恢复检查` | plan_recovery | `.project_os/` exists? | report-only `plan-recovery`; optional generated report |
| `崩溃恢复检查` | plan_recovery | `.project_os/` exists? | report-only `plan-recovery`; no replay/rollback |
| `恢复事件日志` | restore_journal | `.project_os/` exists and `events.jsonl` missing | dry-run `restore-journal`; `--apply --approved` to create missing journal |

### 1.5 Session runtime focus

| User phrase | Intent | Required info | Default action |
|---|---|---|---|
| `新建会话` | create_session | session id | `create-session`; optionally `--set-current` |
| `创建会话` | create_session | session id | `create-session` |
| `切会话` | set_current_session | session id | `set-current-session` |
| `切换会话` | set_current_session | session id | `set-current-session` |
| `列出会话` | list_sessions | none | `list-sessions` |
| `当前会话` | show_current_session | optional session id | `show-session` |
| `更新会话焦点` | set_session_focus | session id + branch/task/run optional | `set-session-focus` |
| `暂停会话` | pause_session | session id | `pause-session` |
| `恢复会话` | resume_session | session id | `resume-session`; optionally `--set-current` |
| `关闭会话` | close_session | session id + confirmation | `close-session` |
| `会话清理` | plan_session_cleanup | optional status/age filters | dry-run/report-only `plan-session-cleanup` |
| `规划会话清理` | plan_session_cleanup | optional status/age filters | `plan-session-cleanup`; optional generated report |

Session routes manipulate runtime focus only. They do not create separate branch/task/run identities; session pointers still resolve to canonical branch/task/run manifests and indexes. Paused and closed sessions cannot become `current_session`; resume a paused session before switching to it.

Session cleanup routes are archive/GC planners only. They may list closed or paused sessions and write generated reports under `.project_os/exports/session_cleanup/`, but they must not delete, move, rewrite, or hide session runtime directories.

### 1.6 Hooks report layer

| User phrase | Intent | Required info | Default action |
|---|---|---|---|
| `hook状态` | list_hooks | none | `list-hooks` |
| `hooks状态` | list_hooks | none | `list-hooks` |
| `列出hooks` | list_hooks | none | `list-hooks` |
| `hook报告` | dispatch_hooks | initialized `.project_os` | `dispatch-hooks --limit 1` |
| `hook提醒` | dispatch_hooks | initialized `.project_os` | `dispatch-hooks --limit 1 --kind reminder` when requested |
| `派发hook` | dispatch_hooks | initialized `.project_os` | manual report-only `dispatch-hooks` |

Hook routes are report-only. They may read `.project_os/journals/events.jsonl` and suggest `project_os.py` commands, but they must not auto-execute suggested commands, edit canonical state, or bypass promotion/release approval gates.

Hook route options mirror the manual dispatcher enough for targeted reports:

- `--event <event_name>` filters events before applying `--limit`.
- `--event-index <line_no>` selects one exact journal line and takes precedence over `--event` / `--limit`.
- `--limit <n>` controls how many recent matching events are included.
- `--kind <session_summary|reminder|opt_in_maintenance|guard>` plans one handler kind; `hook提醒` defaults to `reminder`.
- `--write-report --output <dir>` may be planned, but the output is still a generated inspection view, not canonical state.

### 2. Branch / workstream

| User phrase | Intent | Required info | Default action |
|---|---|---|---|
| `新建分支` | create_branch | branch title or id | Ask if missing; then `create-branch` |
| `新建一个分析分支` | create_branch | branch title/id | `create-branch` |
| `开一个方向` | create_branch | objective/title | `create-branch` |
| `切分支` | set_current_branch | branch id | Ask if missing; then `set-current-branch` |
| `切到这个分支` | set_current_branch | branch id from context | `set-current-branch` |
| `列出分支` | list_branches | none | `list-branches` |
| `当前分支` | show_current_branch | none | `status` or `show-branch` |
| `归档分支` | archive_branch | branch id + confirmation | dry-run/summary, then `archive-branch` |

### 3. Task

| User phrase | Intent | Required info | Default action |
|---|---|---|---|
| `新建任务` | create_task | title | Ask if missing; then `create-task --set-current` |
| `创建任务` | create_task | title | `create-task` |
| `切任务` | set_current_task | task id | `set-current-task` |
| `当前任务` | show_current_task | none | `start` or `show-task` |
| `列出任务` | list_tasks | optional filters | `list-tasks` |
| `任务进入运行阶段` | update_task_stage | task id optional | `update-task-stage --stage Run` |
| `更新任务信息` | update_task | task id + fields | `update-task` |
| `添加依赖` | add_dependency | task id + upstream task/result | `add-dependency` |
| `关闭任务` | close_task | status + confirmation | `close-task` |
| `更新交接` | update_handoff | message | `update-handoff` |

### 4. Run lifecycle

| User phrase | Intent | Required info | Default action |
|---|---|---|---|
| `开始运行` | create_run | current task or task id | `create-run` |
| `开始一次正式运行` | create_run | current task or task id | `create-run` |
| `开run` | create_run | task id if no current task | `create-run` |
| `当前run` | show_current_run | none | `status` or `show-run` |
| `列出run` | list_runs | optional filters | `list-runs` |
| `关闭run` | close_run | run id/status | `close-run` |
| `记录运行输出` | add_run_output | run id + path | `add-run-output` |
| `记录运行命令` | add_run_command | run id + command | `add-run-command` |
| `记录运行指标` | add_run_metric | run id + metric | `add-run-metric` |
| `记录运行参数` | add_run_parameter | run id + key=value | `add-run-parameter` |
| `捕获运行环境` | capture_run_env | run id | `capture-run-env`; optionally add `--pip-freeze --freeze-file <run-relative-path>` |

### 4.5 Project/domain work request

These triggers absorb formerly standalone planning/phylogeny-style prompts so `.project_os` remains the first controller in durable projects.

| User phrase | Intent | State check | Default action |
|---|---|---|---|
| `开始分析` | project_work_request | current task? | if no current task: plan `create-task`; otherwise plan `create-run` |
| `先跑` / `跑一下` | project_work_request | current task? | create/select task, then run under harness |
| `先画` / `画图` / `绘图` | project_work_request | current task? | create/select task, then run and register outputs |
| `生成结果` | project_work_request | current task/run? | create run or register result after output path is known |
| `制定计划` / `拆解任务` | project_work_request | branch/task context | create/update `.project_os` task tree, not `task_plan.md` |
| `plan out` / `break down` / `organize multi-step work` / `5+ tool calls` | project_work_request | branch/task context | create/update `.project_os` task tree, not the old planning-file kernel |
| `task_plan.md` / `findings.md` / `progress.md` | project_work_request | branch/task/session context | route old planning-file references into `.project_os` task/handoff state |
| `系统发育` / `发育树` / `进化树` | project_work_request | branch/task/run context | route through harness before tree/alignment execution |
| `Newick` / `FASTA比对` / `PHYLIP` / `Nexus` | project_work_request | input assets and current task | record assets, command, outputs, and result |
| `alignment` / `tree` / `parsimony` / `treeness` / `RCV` / `DVMC` | project_work_request | input assets and current task | record metric/tree analysis provenance in the current branch/task/run |
| `ortholog` / `同源基因` / `分子进化` / `bootstrap` | project_work_request | input assets and current task | record domain analysis provenance in the current branch/task/run |

### 5. Result lifecycle

| User phrase | Intent | Required info | Default action |
|---|---|---|---|
| `记录结果` | register_result | path + current run/run id | `register-result --status candidate` |
| `登记结果` | register_result | path + current run/run id | `register-result` |
| `记结果` | register_result | path | Ask for path/run if missing |
| `列出结果` | list_results | optional filters | `list-results` |
| `看结果` | show_result | result id | `show-result` |
| `当前结果` / `查看当前结果` | show_current_results | optional scope/branch | read-only `show-current --audit` |
| `接受结果` | accept_result | result id | `accept-result` |
| `设为当前结果` | promote_result | result id + target + confirmation | dry-run `promote-result`; ask before `--apply --approved` |
| `提升结果` | promote_result | result id + target + confirmation | dry-run first |
| `替换当前结果` | promote_result_replace | result id + target + confirmation | dry-run; require explicit replace |
| `废弃结果` | supersede_result | result id + replacement optional | `supersede-result` |

### 6. Data assets

| User phrase | Intent | Required info | Default action |
|---|---|---|---|
| `登记数据` | register_asset | path/source/kind | `register-asset` |
| `登记数据源` | register_asset | source URL/path | `register-asset` |
| `纳管外置数据` | adopt_external_asset | existing external path; optional old-path mappings | dry-run `adopt-external-asset`; apply requires explicit approval |
| `登记外置数据` | adopt_external_asset | existing external path | `adopt-external-asset` |
| `认领外置资产` | adopt_external_asset | existing external path | `adopt-external-asset` |
| `列出数据` | list_assets | optional filters | `list-assets` |
| `检查数据` | show_asset | asset id/path | `show-asset` or `checksum-asset` |
| `规划外置数据` | plan_externalize_assets | optional threshold/roots | report-only `plan-externalize-assets` |
| `外置数据` | externalize_asset | path + primary root | dry-run `externalize-asset`; apply requires explicit approval |
| `验证外置数据` | verify_external_assets | optional asset id | read-only `verify-external-assets` |
| `列出资产位置` | list_asset_locations | optional asset id | `list-asset-locations` |

### 7. Decision / release

| User phrase | Intent | Required info | Default action |
|---|---|---|---|
| `记录决策` | record_decision | title/body | `record-decision` |
| `记录决定` | record_decision | title/body | `record-decision` |
| `总结状态` | summarize_state | none | `summarize-state` |
| `总结项目状态` / `写一个项目状态文档` / `更新项目状态文档` | summarize_state | `.project_os/` exists? | `summarize-state` and keep `PROJECT_STATE.md` thin |
| `记录当前项目进度` / `整理项目当前进展` | summarize_state | `.project_os/` exists? | read-only summary first; update handoff only when explicitly asked |
| `项目文档太大` / `拆分项目文档` | summarize_state | derived indexes and handoff files | keep detail in `.project_os` indexes/views, not a parallel state system |
| `打包release` | build_release | result ids + release id | dry-run `build-release`; ask before `--apply --approved` |
| `发布包` | build_release | result ids + release id | dry-run first |
| `检查release` | validate_release | release id | `validate-release` |

## Ambiguity handling

Ask one concise question only when required information is missing and cannot be inferred safely.

Examples:

- `新建分支` without title/id: ask for branch title or suggested id.
- `记录结果` without path: ask which file/folder to register.
- `设为当前结果` without result id: list candidate results or ask which one.
- `关闭run` with multiple active runs: ask which run id.

Do not ask when state can be safely inferred:

- If `.project_os/runtime/current_task` is set, `开始运行` uses the current task.
- If exactly one active run exists in current task, `记录结果` can use that run after confirming the result path.
- If `.project_os/` exists, `开工` means `start`.

## Safety gates

The router must preserve these gates:

1. `new-project` / `init` on unfamiliar projects starts as dry-run unless user clearly requested apply.
2. `promote-result` starts as dry-run and requires explicit approval for `--apply --approved`.
3. Replacing an existing current result requires explicit replace confirmation.
4. `archive-branch`, `close-task`, and release packaging require clear target IDs.
5. `route --apply` for promotion or release must also include `--approved`; otherwise the route plan stays `ready=false`.
6. No destructive cleanup is routed from short triggers.
7. Hook routes are manual/report-only: `dispatch-hooks` may write generated reports only when explicitly requested with `--write-report`, and those reports are not canonical state.
8. Hook route planning may pass through `--event-index`, `--event`, `--limit`, `--kind`, `--write-report`, and `--output`, but it must not execute hook-suggested commands.
9. Session cleanup routes are dry-run/report-only; physical archive/delete/GC is not routed from short triggers.
10. `恢复事件日志` only plans `restore-journal`; applying it requires explicit `--approved` and creates only the missing journal plus a `journal.restored` event.
11. `恢复计划` / `恢复检查` only plans `plan-recovery`; it may write a generated report, but it must not replay events, roll back operations, delete tmp files, remove locks, or rewrite canonical state.
12. `当前结果` / `查看当前结果` only plans read-only `show-current --audit`; it must not be treated as a promotion request.
13. Asset externalization routes must never plan hard links.
14. `外置数据` defaults to dry-run and requires `--apply --approved` before copy/move.
15. `纳管外置数据` defaults to dry-run and requires `--apply --approved` before writing canonical asset/location state; it never copies or moves the data file.
15. Asset externalization routes must treat symlink compatibility as optional/non-canonical and must not rely on symlinks for recovery.

## Verification after actions

After write actions, run or suggest the smallest relevant verification:

| Intent | Verification |
|---|---|
| bootstrap_project | `status` then `doctor` |
| plan_recovery | optional `doctor --repair-plan`; review generated report if written |
| restore_journal | `validate` then `doctor` |
| create_branch / set_current_branch | `status` or `show-branch` |
| list_hooks / dispatch_hooks | no automatic verification; optional `doctor` if the report suggests it |
| plan_session_cleanup | `list-sessions`; optional `doctor` if stale pointers are reported |
| create_task / set_current_task | `start` or `show-task` |
| create_run / close_run | `show-run` and `refresh-indexes` |
| register_result / promote_result | `show-result`, `RESULTS_INDEX.md`, `refresh-indexes` |
| show_current_results | read-only `show-current --audit` output |
| register_asset | `show-asset` or `DATA_ASSETS.md` |
| build_release | `validate-release` |

## Future slash/command aliases

Later platform adapters may expose slash commands. These are aliases only; they must route to the same intents and CLI commands.

```text
/project-start       -> resume_project
/project-status      -> show_status
/hooks-status        -> list_hooks
/hooks-report        -> dispatch_hooks
/branch-new          -> create_branch
/branch-switch       -> set_current_branch
/task-new            -> create_task
/run-open            -> create_run
/run-close           -> close_run
/result-register     -> register_result
/result-promote      -> promote_result
/release-build       -> build_release
```
