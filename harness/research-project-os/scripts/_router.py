from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def normalize_phrase(text: str) -> str:
    return re.sub(r'\s+', '', (text or '').strip().lower())


ROUTE_PATTERNS: list[tuple[list[str], str, str]] = [
    (['新项目骨架', '搭项目骨架', '初始化项目骨架', 'newproject', 'bootstrapproject'], 'bootstrap_project', 'bootstrap'),
    (['项目骨架', '项目工作流骨架'], 'auto_bootstrap_or_resume', 'bootstrap'),
    (['修复计划', '怎么修', 'repairplan'], 'repair_plan', 'bootstrap'),
    (['检查项目骨架', 'doctor', '诊断项目'], 'doctor_project', 'bootstrap'),
    (['恢复计划', '恢复检查', '崩溃恢复检查', 'recoveryplan', 'planrecovery'], 'plan_recovery', 'bootstrap'),
    (['恢复事件日志', '恢复journal', '恢复日志', 'restorejournal'], 'restore_journal', 'bootstrap'),
    (['总结状态', '总结项目状态', '更新项目状态文档', '写一个项目状态文档', '记录当前项目进度', '整理项目当前进展', '项目文档太大', '拆分项目文档', 'handoff', 'summarizestate'], 'summarize_state', 'decision_release'),
    (['看项目状态', '项目状态', '当前进展', 'status'], 'show_status', 'bootstrap'),
    (['继续当前任务', '继续项目', '继续下一步', '恢复上下文', '大项目', '逐步推进', '大项目逐步推进', '多步骤项目', 'complexproject', 'multistepproject', '开工', 'start', 'resume'], 'resume_project', 'bootstrap'),
    (['hook状态', 'hooks状态', '列出hooks', 'listhooks'], 'list_hooks', 'hooks'),
    (['派发hook', 'hook提醒', 'hook报告', 'dispatchhooks'], 'dispatch_hooks', 'hooks'),
    (['新建会话', '创建会话', 'createsession'], 'create_session', 'session'),
    (['切会话', '切换会话', 'setsession', 'switchsession'], 'set_current_session', 'session'),
    (['列出会话', 'listsessions'], 'list_sessions', 'session'),
    (['当前会话', 'showsession', 'currentsession'], 'show_current_session', 'session'),
    (['更新会话焦点', '设置会话焦点', 'setsessionfocus'], 'set_session_focus', 'session'),
    (['暂停会话', 'pausesession'], 'pause_session', 'session'),
    (['恢复会话', 'resumesession'], 'resume_session', 'session'),
    (['关闭会话', 'closesession'], 'close_session', 'session'),
    (['清理会话', '会话清理', '规划会话清理', 'sessioncleanup'], 'plan_session_cleanup', 'session'),
    (['新建分支', '新建一个分析分支', '开一个方向', 'createbranch'], 'create_branch', 'branch'),
    (['切到这个分支', '切分支', 'switchbranch'], 'set_current_branch', 'branch'),
    (['列出分支', 'listbranches'], 'list_branches', 'branch'),
    (['当前分支', 'currentbranch'], 'show_current_branch', 'branch'),
    (['归档分支', 'archivebranch'], 'archive_branch', 'branch'),
    (['新建任务', '创建任务', 'createtask'], 'create_task', 'task'),
    (['切任务', 'switchtask'], 'set_current_task', 'task'),
    (['列出任务', 'listtasks'], 'list_tasks', 'task'),
    (['当前任务', 'currenttask'], 'show_current_task', 'task'),
    (['任务进入运行阶段'], 'task_stage_run', 'task'),
    (['更新任务信息'], 'update_task', 'task'),
    (['添加依赖'], 'add_dependency', 'task'),
    (['关闭任务'], 'close_task', 'task'),
    (['更新交接', '更新handoff'], 'update_handoff', 'task'),
    (['开始一次正式运行', '开始运行', '开run', 'createrun'], 'create_run', 'run'),
    (['当前run', '当前运行', 'currentrun'], 'show_current_run', 'run'),
    (['列出run', '列出运行', 'listruns'], 'list_runs', 'run'),
    (['关闭run', '关闭运行'], 'close_run', 'run'),
    (['记录运行输出'], 'add_run_output', 'run'),
    (['记录运行命令'], 'add_run_command', 'run'),
    (['记录运行指标'], 'add_run_metric', 'run'),
    (['记录运行参数'], 'add_run_parameter', 'run'),
    (['捕获运行环境'], 'capture_run_env', 'run'),
    (['记录结果', '登记结果', '记结果', 'registerresult'], 'register_result', 'result'),
    (['列出结果', 'listresults'], 'list_results', 'result'),
    (['看结果', 'showresult'], 'show_result', 'result'),
    (['接受结果', 'acceptresult'], 'accept_result', 'result'),
    (['设为当前结果', '提升结果', 'promoteresult'], 'promote_result', 'result'),
    (['替换当前结果'], 'promote_result_replace', 'result'),
    (['查看当前结果', '当前结果', 'currentresults', 'showcurrent'], 'show_current_results', 'result'),
    (['废弃结果', 'supersede'], 'supersede_result', 'result'),
    (['登记数据源', '登记数据', 'registerasset'], 'register_asset', 'asset'),
    (['纳管外置数据', '纳管外置资产', '登记外置数据', '认领外置资产', 'adoptexternalasset'], 'adopt_external_asset', 'asset'),
    (['列出数据', 'listassets'], 'list_assets', 'asset'),
    (['检查数据', 'showasset'], 'show_asset', 'asset'),
    (['规划外置数据', '规划外置资产', 'planexternalizeassets'], 'plan_externalize_assets', 'asset'),
    (['外置数据', '外置资产', 'externalizeasset'], 'externalize_asset', 'asset'),
    (['验证外置数据', '验证外置资产', 'verifyexternalassets'], 'verify_external_assets', 'asset'),
    (['列出资产位置', '列出外置位置', 'listassetlocations'], 'list_asset_locations', 'asset'),
    (['记录决策', '记录决定'], 'record_decision', 'decision_release'),
    (['打包release', '发布包', 'buildrelease'], 'build_release', 'decision_release'),
    (['检查release', 'validaterelease'], 'validate_release', 'decision_release'),
    ([
        '开始分析', '先跑', '跑一下', '先画', '画图', '绘图', '生成结果', '制定计划', '拆解任务',
        'planout', 'breakdown', 'breakdownproject', 'organizemultistepwork', 'organizemulti-stepwork', '5+toolcalls',
        'task_plan.md', 'findings.md', 'progress.md',
        '系统发育', '发育树', '进化树', 'newick', 'fasta比对', 'phylip', 'nexus',
        'treeness', 'rcv', 'dvmc', 'parsimony', 'alignment', 'tree',
        'ortholog', '同源基因', '分子进化', 'bootstrap',
    ], 'project_work_request', 'work'),
]


def resolve_route_intent(phrase: str) -> tuple[str, str, str]:
    normalized = normalize_phrase(phrase)
    for patterns, intent, group in ROUTE_PATTERNS:
        for pattern in patterns:
            if normalize_phrase(pattern) in normalized:
                return intent, group, pattern
    return 'unknown', 'unknown', ''


def planned_command(root: Path, subcommand: str, extra: list[str] | None = None) -> dict[str, Any]:
    argv = [sys.executable, (Path(__file__).resolve().parent / 'project_os.py').as_posix(), subcommand, '--root', root.as_posix()]
    if extra:
        argv.extend([str(item) for item in extra])
    return {'argv': argv, 'shell': ' '.join(shlex.quote(part) for part in argv)}


def route_state(ctx: Any, root: Path) -> dict[str, Any]:
    initialized = (ctx.project_os(root) / 'workflow.md').exists()
    state: dict[str, Any] = {
        'initialized': initialized,
        'current_session': ctx.current_session(root) if initialized and hasattr(ctx, 'current_session') else '',
        'current_branch': ctx.current_pointer(root, 'current_branch') if initialized else '',
        'current_task': ctx.current_pointer(root, 'current_task') if initialized else '',
        'current_run': ctx.current_pointer(root, 'current_run') if initialized else '',
        'counts': {},
    }
    if initialized:
        state['counts'] = {
            'branches': ctx.count_rows(ctx.indexes_dir(root) / 'branches.tsv'),
            'tasks': ctx.count_rows(ctx.indexes_dir(root) / 'tasks.tsv'),
            'runs': ctx.count_rows(ctx.indexes_dir(root) / 'runs.tsv'),
            'results': ctx.count_rows(ctx.indexes_dir(root) / 'results.tsv'),
            'assets': ctx.count_rows(ctx.indexes_dir(root) / 'assets.tsv'),
            'releases': ctx.count_rows(ctx.indexes_dir(root) / 'releases.tsv'),
            'sessions': len(ctx.session_summary_for_dashboard(root).get('sessions', [])) if hasattr(ctx, 'session_summary_for_dashboard') else 0,
        }
    return state


def route_single(items: Any) -> str:
    if isinstance(items, list):
        return str(items[0]) if items else ''
    return str(items or '')


def infer_route_run(ctx: Any, root: Path, args: argparse.Namespace, task_id: str = '') -> tuple[str, str]:
    if getattr(args, 'run_id', ''):
        return args.run_id, 'explicit'
    current = ctx.current_pointer(root, 'current_run')
    if current:
        return current, 'current_run'
    if task_id:
        active = [row for row in ctx.read_tsv(ctx.indexes_dir(root) / 'runs.tsv') if row.get('task_id') == task_id and row.get('status') in {'active', 'pending_review'}]
        if len(active) == 1:
            return active[0].get('run_id', ''), 'single_active_run_for_task'
    return '', 'missing'


def route_verification(ctx: Any, root: Path, intent: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    result_id = route_single(getattr(args, 'result_id', ''))
    release_id = getattr(args, 'release_id', '')
    checks: list[dict[str, Any]] = []
    if intent in {'bootstrap_project', 'auto_bootstrap_or_resume'}:
        checks = [planned_command(root, 'status'), planned_command(root, 'doctor')]
    elif intent in {'resume_project', 'show_status', 'doctor_project', 'repair_plan', 'plan_recovery'}:
        checks = []
    elif intent == 'restore_journal':
        checks = [planned_command(root, 'validate'), planned_command(root, 'doctor')]
    elif intent in {'list_hooks', 'dispatch_hooks'}:
        checks = []
    elif intent in {'create_session', 'set_current_session', 'set_session_focus', 'pause_session', 'resume_session', 'close_session', 'show_current_session'}:
        sid = getattr(args, 'session_id', '') or state_current_session(ctx, root)
        checks = [planned_command(root, 'show-session', ['--session-id', sid])] if sid else [planned_command(root, 'list-sessions')]
    elif intent in {'list_sessions', 'plan_session_cleanup'}:
        checks = [planned_command(root, 'list-sessions')]
    elif intent in {'create_branch', 'set_current_branch', 'archive_branch', 'show_current_branch', 'list_branches'}:
        checks = [planned_command(root, 'status')]
    elif intent == 'project_work_request':
        checks = [planned_command(root, 'start')]
    elif intent in {'create_task', 'set_current_task', 'show_current_task', 'task_stage_run', 'update_task', 'add_dependency', 'close_task', 'update_handoff'}:
        task_id = getattr(args, 'task_id', '') or (f"{datetime.now().strftime('%Y%m%d')}_{ctx.slugify(getattr(args, 'title', ''))}" if intent == 'create_task' and getattr(args, 'title', '') else '') or ctx.current_pointer(root, 'current_task')
        checks = [planned_command(root, 'show-task', ['--task-id', task_id])] if task_id else [planned_command(root, 'start')]
    elif intent in {'create_run', 'show_current_run', 'close_run', 'add_run_output', 'add_run_command', 'add_run_metric', 'add_run_parameter', 'capture_run_env'}:
        run_id, _ = infer_route_run(ctx, root, args, getattr(args, 'task_id', '') or ctx.current_pointer(root, 'current_task'))
        checks = [planned_command(root, 'show-run', ['--run-id', run_id])] if run_id else [planned_command(root, 'list-runs')]
    elif intent in {'register_result', 'accept_result', 'promote_result', 'promote_result_replace', 'supersede_result', 'show_result'}:
        checks = [planned_command(root, 'show-result', ['--result-id', result_id])] if result_id else [planned_command(root, 'list-results')]
    elif intent == 'show_current_results':
        checks = []
    elif intent in {'register_asset', 'adopt_external_asset', 'show_asset', 'plan_externalize_assets', 'externalize_asset', 'verify_external_assets', 'list_asset_locations'}:
        asset_id = getattr(args, 'asset_id', '')
        if intent == 'plan_externalize_assets':
            checks = [planned_command(root, 'list-assets'), planned_command(root, 'list-asset-locations')]
        elif intent == 'list_asset_locations':
            checks = [planned_command(root, 'list-asset-locations', ['--asset-id', asset_id])] if asset_id else [planned_command(root, 'list-asset-locations')]
        elif intent == 'verify_external_assets':
            checks = [planned_command(root, 'list-asset-locations', ['--asset-id', asset_id])] if asset_id else [planned_command(root, 'list-asset-locations')]
        elif intent == 'adopt_external_asset':
            checks = [planned_command(root, 'show-asset', ['--asset-id', asset_id])] if asset_id else [planned_command(root, 'list-assets'), planned_command(root, 'list-asset-locations')]
        else:
            checks = [planned_command(root, 'show-asset', ['--asset-id', asset_id])] if asset_id else [planned_command(root, 'list-assets')]
    elif intent == 'build_release':
        checks = [planned_command(root, 'validate-release', ['--release-id', release_id])] if release_id else [planned_command(root, 'list-releases')]
    elif intent == 'validate_release':
        checks = []
    if intent not in {'auto_bootstrap_or_resume', 'bootstrap_project', 'show_status', 'doctor_project', 'repair_plan', 'plan_recovery', 'restore_journal', 'resume_project', 'list_hooks', 'dispatch_hooks', 'list_branches', 'list_tasks', 'list_runs', 'list_results', 'show_current_results', 'list_assets', 'summarize_state'}:
        checks.append(planned_command(root, 'doctor'))
    return checks


def add_missing(missing: list[str], name: str) -> None:
    if name not in missing:
        missing.append(name)


def state_current_session(ctx: Any, root: Path) -> str:
    return ctx.current_session(root) if hasattr(ctx, 'current_session') else ''


def build_route_plan(ctx: Any, root: Path, args: argparse.Namespace) -> dict[str, Any]:
    phrase = args.phrase
    intent, group, matched_pattern = resolve_route_intent(phrase)
    state = route_state(ctx, root)
    missing: list[str] = []
    commands: list[dict[str, Any]] = []
    safety: list[str] = []
    notes: list[str] = []

    initialized = bool(state['initialized'])
    title = getattr(args, 'title', '') or ''
    branch_id = getattr(args, 'branch_id', '') or ''
    session_id = getattr(args, 'session_id', '') or ''
    task_id = getattr(args, 'task_id', '') or (ctx.current_pointer(root, 'current_task') if initialized else '')
    run_id, run_source = infer_route_run(ctx, root, args, task_id) if initialized else ('', 'uninitialized')
    result_id = route_single(getattr(args, 'result_id', ''))
    path = getattr(args, 'path', '') or ''

    if intent == 'unknown':
        notes.append('No router pattern matched. Ask one concise clarification question, or use a full project_os.py command.')
    elif intent == 'auto_bootstrap_or_resume':
        if initialized:
            commands.append(planned_command(root, 'start'))
        else:
            extra = ['--title', title or root.name]
            if args.apply:
                extra.append('--apply')
            else:
                safety.append('Unfamiliar project: dry-run new-project first; add route --apply only after review.')
            commands.append(planned_command(root, 'new-project', extra))
    elif intent == 'bootstrap_project':
        extra = ['--title', title or root.name]
        if args.apply:
            extra.append('--apply')
        else:
            safety.append('Bootstrap is dry-run by default; review created paths before applying.')
        commands.append(planned_command(root, 'new-project', extra))
    elif intent == 'resume_project':
        if not initialized:
            commands.append(planned_command(root, 'new-project', ['--title', title or root.name]))
            safety.append('Project is not initialized; route falls back to bootstrap dry-run.')
        else:
            commands.append(planned_command(root, 'start'))
    elif intent == 'show_status':
        commands.append(planned_command(root, 'status'))
    elif intent == 'doctor_project':
        commands.append(planned_command(root, 'doctor'))
    elif intent == 'repair_plan':
        commands.append(planned_command(root, 'doctor', ['--repair-plan']))
    elif intent == 'plan_recovery':
        extra: list[str] = []
        if getattr(args, 'max_lock_age_seconds', 300) != 300:
            extra += ['--max-lock-age-seconds', str(max(0, int(getattr(args, 'max_lock_age_seconds', 300) or 0)))]
        if getattr(args, 'max_tmp_files', 200) != 200:
            extra += ['--max-tmp-files', str(max(0, int(getattr(args, 'max_tmp_files', 200) or 0)))]
        if getattr(args, 'write_report', False):
            extra.append('--write-report')
            if getattr(args, 'output', ''):
                extra += ['--output', args.output]
            safety.append('Recovery reports are generated inspection views; writing a report does not replay, roll back, delete tmp files, or remove locks.')
        safety.append('plan-recovery is report-only and never changes canonical state or performs crash replay.')
        commands.append(planned_command(root, 'plan-recovery', extra))
    elif intent == 'restore_journal':
        if not initialized:
            add_missing(missing, '.project_os initialized')
            commands.append(planned_command(root, 'new-project', ['--title', title or root.name]))
            safety.append('restore-journal requires an initialized/adopted harness; bootstrap dry-run first.')
        else:
            extra: list[str] = []
            if args.apply:
                if args.approved:
                    extra.append('--apply')
                    extra.append('--approved')
                    safety.append('restore-journal apply creates only a missing events.jsonl and appends journal.restored.')
                else:
                    add_missing(missing, 'approved restore-journal confirmation')
                    safety.append('restore-journal writes canonical event source; rerun route with --approved after reviewing doctor output.')
            else:
                safety.append('restore-journal is dry-run by default; add --apply --approved only when events.jsonl is truly missing.')
            if args.notes:
                extra += ['--reason', args.notes]
            commands.append(planned_command(root, 'restore-journal', extra))
    elif intent == 'list_hooks':
        commands.append(planned_command(root, 'list-hooks'))
    elif intent == 'dispatch_hooks':
        if not initialized:
            add_missing(missing, '.project_os initialized')
            safety.append('Hook reports consume .project_os/journals/events.jsonl; initialize/adopt the project first.')
        else:
            extra: list[str] = []
            if getattr(args, 'event_index', 0):
                extra += ['--event-index', str(args.event_index)]
            else:
                if getattr(args, 'event', ''):
                    extra += ['--event', args.event]
                extra += ['--limit', str(max(1, int(getattr(args, 'limit', 1) or 1)))]
            hook_kind = args.kind or ('reminder' if '提醒' in phrase.lower() else '')
            if hook_kind:
                extra += ['--kind', hook_kind]
            if getattr(args, 'write_report', False):
                extra.append('--write-report')
                if getattr(args, 'output', ''):
                    extra += ['--output', args.output]
                safety.append('Hook report writing is limited to generated views; .project_os/exports/hooks is not canonical state.')
            safety.append('Hook routes are manual/report-only and do not execute suggested commands or edit canonical state.')
            commands.append(planned_command(root, 'dispatch-hooks', extra))
    elif not initialized:
        add_missing(missing, '.project_os initialized')
        commands.append(planned_command(root, 'new-project', ['--title', title or root.name]))
        safety.append('Initialize/adopt the project before branch/task/run/result operations.')
    elif intent == 'project_work_request':
        work_title = title or phrase.strip() or 'project work'
        if not task_id:
            extra = ['--title', work_title, '--kind', args.kind or 'analysis', '--set-current']
            if branch_id:
                extra += ['--branch-id', branch_id]
            commands.append(planned_command(root, 'create-task', extra))
            notes.append('Project/domain work request detected. Create or select a harness task first, then execute analysis inside that branch/task context.')
        else:
            slug = ctx.slugify(work_title) if hasattr(ctx, 'slugify') else 'project_work'
            commands.append(planned_command(root, 'create-run', ['--task-id', task_id, '--slug', slug or 'project_work']))
            notes.append('Project/domain work request detected. Use the current task, create a run, then record commands, outputs, results, and assets.')
    elif intent == 'create_session':
        if not session_id:
            add_missing(missing, 'session_id')
        else:
            extra = ['--session-id', session_id]
            if title:
                extra += ['--title', title]
            if branch_id:
                extra += ['--branch-id', branch_id]
            if getattr(args, 'task_id', ''):
                extra += ['--task-id', args.task_id]
            if getattr(args, 'run_id', ''):
                extra += ['--run-id', args.run_id]
            if getattr(args, 'set_current', False):
                extra.append('--set-current')
            if args.notes:
                extra += ['--notes', args.notes]
            commands.append(planned_command(root, 'create-session', extra))
    elif intent == 'set_current_session':
        if not session_id:
            add_missing(missing, 'session_id')
        else:
            commands.append(planned_command(root, 'set-current-session', ['--session-id', session_id]))
    elif intent == 'list_sessions':
        commands.append(planned_command(root, 'list-sessions'))
    elif intent == 'show_current_session':
        extra = ['--session-id', session_id] if session_id else []
        commands.append(planned_command(root, 'show-session', extra))
    elif intent == 'set_session_focus':
        if not session_id:
            add_missing(missing, 'session_id')
        if session_id:
            extra = ['--session-id', session_id]
            if branch_id:
                extra += ['--branch-id', branch_id]
            if getattr(args, 'task_id', ''):
                extra += ['--task-id', args.task_id]
            if getattr(args, 'run_id', ''):
                extra += ['--run-id', args.run_id]
            if getattr(args, 'set_current', False):
                extra.append('--set-current')
            if args.notes:
                extra += ['--notes', args.notes]
            commands.append(planned_command(root, 'set-session-focus', extra))
    elif intent == 'pause_session':
        if not session_id:
            add_missing(missing, 'session_id')
        if session_id:
            extra = ['--session-id', session_id]
            if args.notes:
                extra += ['--notes', args.notes]
            commands.append(planned_command(root, 'pause-session', extra))
            safety.append('pause-session only changes session lifecycle/focus overlay; it does not change canonical branch/task/run state.')
    elif intent == 'resume_session':
        if not session_id:
            add_missing(missing, 'session_id')
        if session_id:
            extra = ['--session-id', session_id]
            if getattr(args, 'set_current', False):
                extra.append('--set-current')
            if args.notes:
                extra += ['--notes', args.notes]
            commands.append(planned_command(root, 'resume-session', extra))
            safety.append('resume-session restores a session focus overlay; it does not create branch/task/run identities or bypass approval gates.')
    elif intent == 'close_session':
        if not session_id:
            add_missing(missing, 'session_id')
        if not args.approved:
            add_missing(missing, 'approved close-session confirmation')
            safety.append('close-session changes runtime focus lifecycle; require explicit approval.')
        if session_id and args.approved:
            extra = ['--session-id', session_id]
            if args.notes:
                extra += ['--notes', args.notes]
            commands.append(planned_command(root, 'close-session', extra))
    elif intent == 'plan_session_cleanup':
        extra: list[str] = []
        if args.status:
            extra += ['--status', args.status]
        if getattr(args, 'min_age_days', 0):
            extra += ['--min-age-days', str(max(0, int(args.min_age_days or 0)))]
        if getattr(args, 'include_current', False):
            extra.append('--include-current')
        if getattr(args, 'write_report', False):
            extra.append('--write-report')
            if getattr(args, 'output', ''):
                extra += ['--output', args.output]
            safety.append('Session cleanup report writing is limited to generated views; it does not delete or move session directories.')
        safety.append('Session cleanup is report-only/dry-run by default and never rewrites canonical branch/task/run/result state.')
        commands.append(planned_command(root, 'plan-session-cleanup', extra))
    elif intent == 'create_branch':
        if not title and not branch_id:
            add_missing(missing, 'branch title or branch_id')
        else:
            extra = ['--title', title or branch_id]
            if branch_id:
                extra += ['--branch-id', branch_id]
            if getattr(args, 'set_current', False):
                extra.append('--set-current')
            if args.notes:
                extra += ['--notes', args.notes]
            commands.append(planned_command(root, 'create-branch', extra))
    elif intent == 'set_current_branch':
        if not branch_id:
            add_missing(missing, 'branch_id')
        else:
            commands.append(planned_command(root, 'set-current-branch', ['--branch-id', branch_id]))
    elif intent == 'list_branches':
        commands.append(planned_command(root, 'list-branches'))
    elif intent == 'show_current_branch':
        commands.append(planned_command(root, 'show-branch', ['--branch-id', branch_id or state.get('current_branch') or ctx.DEFAULT_BRANCH]))
    elif intent == 'archive_branch':
        if not branch_id:
            add_missing(missing, 'branch_id')
        if not args.approved:
            add_missing(missing, 'approved archive confirmation')
            safety.append('archive-branch is non-destructive to files but changes branch lifecycle; require explicit approval.')
        if branch_id and args.approved:
            extra = ['--branch-id', branch_id, '--status', args.status or 'archived']
            if args.notes:
                extra += ['--notes', args.notes]
            commands.append(planned_command(root, 'archive-branch', extra))
    elif intent == 'create_task':
        if not title:
            add_missing(missing, 'task title')
        else:
            extra = ['--title', title, '--kind', args.kind or 'analysis', '--set-current']
            if branch_id:
                extra += ['--branch-id', branch_id]
            if args.notes:
                extra += ['--notes', args.notes]
            commands.append(planned_command(root, 'create-task', extra))
    elif intent == 'set_current_task':
        if not getattr(args, 'task_id', ''):
            add_missing(missing, 'task_id')
        else:
            commands.append(planned_command(root, 'set-current-task', ['--task-id', args.task_id]))
    elif intent == 'list_tasks':
        extra = []
        if branch_id:
            extra += ['--branch-id', branch_id]
        if args.status:
            extra += ['--status', args.status]
        commands.append(planned_command(root, 'list-tasks', extra))
    elif intent == 'show_current_task':
        if not task_id:
            add_missing(missing, 'task_id or current_task')
        else:
            commands.append(planned_command(root, 'show-task', ['--task-id', task_id]))
    elif intent == 'task_stage_run':
        if not task_id:
            add_missing(missing, 'task_id or current_task')
        else:
            commands.append(planned_command(root, 'update-task-stage', ['--task-id', task_id, '--stage', args.stage or 'Run']))
    elif intent == 'update_task':
        if not task_id:
            add_missing(missing, 'task_id or current_task')
        else:
            extra = ['--task-id', task_id]
            if title:
                extra += ['--title', title]
            if args.kind:
                extra += ['--kind', args.kind]
            if args.status:
                extra += ['--status', args.status]
            if args.notes:
                extra += ['--notes', args.notes]
            commands.append(planned_command(root, 'update-task', extra))
    elif intent == 'add_dependency':
        if not task_id:
            add_missing(missing, 'task_id or current_task')
        if not args.depends_on_task and not args.depends_on_result:
            add_missing(missing, 'depends_on_task or depends_on_result')
        if task_id and (args.depends_on_task or args.depends_on_result):
            extra = ['--task-id', task_id]
            for dep in args.depends_on_task:
                extra += ['--depends-on-task', dep]
            for dep in args.depends_on_result:
                extra += ['--depends-on-result', dep]
            commands.append(planned_command(root, 'add-dependency', extra))
    elif intent == 'close_task':
        if not task_id:
            add_missing(missing, 'task_id or current_task')
        if not args.status:
            add_missing(missing, 'task close status')
        if task_id and args.status:
            commands.append(planned_command(root, 'close-task', ['--task-id', task_id, '--status', args.status] + (['--notes', args.notes] if args.notes else [])))
    elif intent == 'update_handoff':
        if not args.body and not args.notes:
            add_missing(missing, 'handoff message')
        else:
            scope = 'task' if task_id else 'branch'
            commands.append(planned_command(root, 'update-handoff', ['--scope', scope, '--message', args.body or args.notes]))
    elif intent == 'create_run':
        if not task_id:
            add_missing(missing, 'task_id or current_task')
        else:
            commands.append(planned_command(root, 'create-run', ['--task-id', task_id, '--slug', title or 'formal_run']))
    elif intent == 'show_current_run':
        if not run_id:
            add_missing(missing, 'run_id or current_run')
        else:
            commands.append(planned_command(root, 'show-run', ['--run-id', run_id]))
    elif intent == 'list_runs':
        extra = []
        if branch_id:
            extra += ['--branch-id', branch_id]
        if task_id:
            extra += ['--task-id', task_id]
        if args.status:
            extra += ['--status', args.status]
        commands.append(planned_command(root, 'list-runs', extra))
    elif intent == 'close_run':
        if not run_id:
            add_missing(missing, 'run_id or current_run')
        if not args.status:
            add_missing(missing, 'run close status')
        if run_id and args.status:
            commands.append(planned_command(root, 'close-run', ['--run-id', run_id, '--status', args.status] + (['--notes', args.notes] if args.notes else [])))
    elif intent == 'add_run_output':
        if not run_id:
            add_missing(missing, 'run_id or current_run')
        if not path:
            add_missing(missing, 'output path')
        if run_id and path:
            commands.append(planned_command(root, 'add-run-output', ['--run-id', run_id, '--path', path, '--kind', args.kind or 'artifact']))
    elif intent == 'add_run_command':
        if not run_id:
            add_missing(missing, 'run_id or current_run')
        if not args.run_command:
            add_missing(missing, 'run_command')
        if run_id and args.run_command:
            commands.append(planned_command(root, 'add-run-command', ['--run-id', run_id, '--command', args.run_command]))
    elif intent == 'add_run_metric':
        if not run_id:
            add_missing(missing, 'run_id or current_run')
        if not args.metric_name or not args.metric_value:
            add_missing(missing, 'metric_name and metric_value')
        if run_id and args.metric_name and args.metric_value:
            commands.append(planned_command(root, 'add-run-metric', ['--run-id', run_id, '--name', args.metric_name, '--value', args.metric_value]))
    elif intent == 'add_run_parameter':
        if not run_id:
            add_missing(missing, 'run_id or current_run')
        if not args.param:
            add_missing(missing, 'param key=value')
        if run_id and args.param:
            extra = ['--run-id', run_id]
            for param in args.param:
                extra += ['--param', param]
            commands.append(planned_command(root, 'add-run-parameter', extra))
    elif intent == 'capture_run_env':
        if not run_id:
            add_missing(missing, 'run_id or current_run')
        else:
            extra = ['--run-id', run_id]
            if getattr(args, 'pip_freeze', False):
                extra.append('--pip-freeze')
                if getattr(args, 'freeze_file', ''):
                    extra += ['--freeze-file', args.freeze_file]
            commands.append(planned_command(root, 'capture-run-env', extra))
    elif intent == 'register_result':
        if not run_id:
            add_missing(missing, 'run_id or current_run')
        if not path:
            add_missing(missing, 'result path')
        if (args.status or 'candidate') in {'accepted', 'current', 'release'} and not args.approved:
            add_missing(missing, 'approved result registration confirmation')
            safety.append('Registering accepted/current/release results requires explicit approval.')
        if run_id and path:
            extra = ['--run-id', run_id, '--path', path, '--status', args.status or 'candidate', '--type', args.kind or 'artifact']
            if args.approved:
                extra.append('--approved')
            commands.append(planned_command(root, 'register-result', extra))
            notes.append(f'run_id inferred from {run_source}.')
    elif intent == 'list_results':
        extra = []
        if branch_id:
            extra += ['--branch-id', branch_id]
        if task_id:
            extra += ['--task-id', task_id]
        if args.status:
            extra += ['--status', args.status]
        commands.append(planned_command(root, 'list-results', extra))
    elif intent == 'show_result':
        if not result_id:
            add_missing(missing, 'result_id')
        else:
            commands.append(planned_command(root, 'show-result', ['--result-id', result_id]))
    elif intent == 'show_current_results':
        scope = getattr(args, 'scope', 'all') or 'all'
        if branch_id and scope == 'all':
            scope = 'branch'
        extra = ['--scope', scope]
        if scope == 'branch' and branch_id:
            extra += ['--branch-id', branch_id]
        if getattr(args, 'audit', True):
            extra.append('--audit')
        commands.append(planned_command(root, 'show-current', extra))
        safety.append('show-current is a read-only derived current-result view; it does not promote, repair, or rewrite result/current state.')
    elif intent == 'accept_result':
        if not result_id:
            add_missing(missing, 'result_id')
        if not args.approved:
            add_missing(missing, 'approved accept confirmation')
            safety.append('accept-result requires --approved because accepted results can enter releases.')
        if result_id and args.approved:
            commands.append(planned_command(root, 'accept-result', ['--result-id', result_id, '--approved'] + (['--notes', args.notes] if args.notes else [])))
    elif intent in {'promote_result', 'promote_result_replace'}:
        if not result_id:
            add_missing(missing, 'result_id')
        target = args.to or (f"current/branches/{branch_id or state.get('current_branch') or ctx.DEFAULT_BRANCH}/{result_id}" if result_id else '')
        if not target:
            add_missing(missing, 'promotion target under current/')
        extra = ['--result-id', result_id, '--to', target] if result_id and target else []
        promoted_exists = (root / target).exists() if target and not Path(target).is_absolute() else (Path(target).exists() if target else False)
        if intent == 'promote_result_replace' or args.replace:
            extra.append('--replace')
        elif promoted_exists:
            add_missing(missing, 'replace confirmation for existing promotion target')
            safety.append('Promotion target already exists; use --replace only after explicit confirmation.')
        if args.apply:
            if args.approved:
                extra.append('--apply')
                extra.append('--approved')
                safety.append('Promotion apply requested with explicit approval.')
            else:
                add_missing(missing, 'approved promotion confirmation')
                safety.append('Promotion apply changes current/ state; rerun the route with --approved only after user approval.')
        else:
            safety.append('Promotion defaults to dry-run; rerun with --apply after reviewing the target.')
        if extra:
            commands.append(planned_command(root, 'promote-result', extra))
    elif intent == 'supersede_result':
        if not result_id:
            add_missing(missing, 'result_id')
        if not args.approved:
            add_missing(missing, 'approved supersede confirmation')
        if result_id and args.approved:
            extra = ['--result-id', result_id, '--approved']
            if args.replaced_by:
                extra += ['--replaced-by', args.replaced_by]
            commands.append(planned_command(root, 'supersede-result', extra))
    elif intent == 'register_asset':
        if not path and not args.source_url:
            add_missing(missing, 'asset path or source_url')
        else:
            extra = ['--kind', args.kind or 'data']
            if path:
                extra += ['--path', path]
            if args.source_url:
                extra += ['--source-url', args.source_url]
            if run_id:
                extra += ['--run-id', run_id]
            commands.append(planned_command(root, 'register-asset', extra))
    elif intent == 'adopt_external_asset':
        if not path:
            add_missing(missing, 'external asset path')
        extra = ['--path', path] if path else []
        if getattr(args, 'asset_id', ''):
            extra += ['--asset-id', args.asset_id]
        if getattr(args, 'kind', ''):
            extra += ['--kind', args.kind]
        for old_path in getattr(args, 'old_path', []) or []:
            extra += ['--old-path', old_path]
        for backup_path in getattr(args, 'backup_path', []) or []:
            extra += ['--backup-path', backup_path]
        for mirror_path in getattr(args, 'mirror_path', []) or []:
            extra += ['--mirror-path', mirror_path]
        for archive_path in getattr(args, 'archive_path', []) or []:
            extra += ['--archive-path', archive_path]
        if run_id:
            extra += ['--run-id', run_id]
        if getattr(args, 'task_id', ''):
            extra += ['--task-id', args.task_id]
        if branch_id:
            extra += ['--branch-id', branch_id]
        if args.notes:
            extra += ['--notes', args.notes]
        if getattr(args, 'write_report', False):
            extra.append('--write-report')
            if getattr(args, 'output', ''):
                extra += ['--output', args.output]
        if args.apply:
            if args.approved:
                extra += ['--apply', '--approved']
                safety.append('adopt-external-asset apply is registry-only: it records asset/location rows and optional usage links without copying, moving, hard-linking, or symlinking data.')
            else:
                add_missing(missing, 'approved adopt confirmation')
                safety.append('adopt-external-asset apply writes canonical asset/location state; rerun route with --approved only after reviewing the dry-run report.')
        else:
            safety.append('adopt-external-asset defaults to dry-run; review old-path mappings and checksum status before applying. It never copies or moves the external file.')
        if extra:
            commands.append(planned_command(root, 'adopt-external-asset', extra))
    elif intent == 'list_assets':
        commands.append(planned_command(root, 'list-assets'))
    elif intent == 'show_asset':
        if not args.asset_id:
            add_missing(missing, 'asset_id')
        else:
            commands.append(planned_command(root, 'show-asset', ['--asset-id', args.asset_id]))
    elif intent == 'plan_externalize_assets':
        extra = ['--threshold', getattr(args, 'threshold', '') or '500M']
        if getattr(args, 'primary_root', ''):
            extra += ['--primary-root', args.primary_root]
        if getattr(args, 'backup_root', ''):
            extra += ['--backup-root', args.backup_root]
        route_mode = getattr(args, 'mode', '') or getattr(args, 'kind', '')
        if route_mode in {'copy', 'move'}:
            extra += ['--mode', route_mode]
        if getattr(args, 'max_files', 0):
            extra += ['--max-files', str(max(0, int(args.max_files or 0)))]
        if getattr(args, 'max_depth', 0):
            extra += ['--max-depth', str(max(0, int(args.max_depth or 0)))]
        if getattr(args, 'write_report', False):
            extra.append('--write-report')
            if getattr(args, 'output', ''):
                extra += ['--output', args.output]
        safety.append('plan-externalize-assets is read-only/report-only and never copies, moves, hard-links, symlinks, deletes, or rewrites canonical state.')
        commands.append(planned_command(root, 'plan-externalize-assets', extra))
    elif intent == 'externalize_asset':
        if not path:
            add_missing(missing, 'asset path')
        extra = ['--path', path] if path else []
        if getattr(args, 'asset_id', ''):
            extra += ['--asset-id', args.asset_id]
        if getattr(args, 'kind', ''):
            extra += ['--kind', args.kind]
        if getattr(args, 'primary_root', ''):
            extra += ['--primary-root', args.primary_root]
        if getattr(args, 'backup_root', ''):
            extra += ['--backup-root', args.backup_root]
        if getattr(args, 'dest_subpath', ''):
            extra += ['--dest-subpath', args.dest_subpath]
        route_mode = getattr(args, 'mode', '') or ''
        if route_mode not in {'copy', 'move'}:
            route_mode = 'copy'
        extra += ['--mode', route_mode]
        if run_id:
            extra += ['--run-id', run_id]
        if getattr(args, 'task_id', ''):
            extra += ['--task-id', args.task_id]
        if branch_id:
            extra += ['--branch-id', branch_id]
        if args.notes:
            extra += ['--notes', args.notes]
        if getattr(args, 'write_report', False):
            extra.append('--write-report')
            if getattr(args, 'output', ''):
                extra += ['--output', args.output]
        if args.apply:
            if args.approved:
                extra += ['--apply', '--approved']
                safety.append('externalize-asset apply uses copy/move + checksum verification + asset/location registration; hard links remain forbidden.')
            else:
                add_missing(missing, 'approved externalize confirmation')
                safety.append('externalize-asset changes canonical asset/location state and may move/copy large files; rerun route with --approved only after review.')
        else:
            safety.append('externalize-asset defaults to dry-run; review mapping/report before applying. Hard links are forbidden and symlinks are non-canonical.')
        if extra:
            commands.append(planned_command(root, 'externalize-asset', extra))
    elif intent == 'verify_external_assets':
        extra: list[str] = []
        if getattr(args, 'asset_id', ''):
            extra += ['--asset-id', args.asset_id]
        if getattr(args, 'audit', False):
            extra.append('--checksum')
        safety.append('verify-external-assets is read-only; it checks availability/checksums and does not repair paths or rewrite location rows.')
        commands.append(planned_command(root, 'verify-external-assets', extra))
    elif intent == 'list_asset_locations':
        extra: list[str] = []
        if getattr(args, 'asset_id', ''):
            extra += ['--asset-id', args.asset_id]
        if args.status:
            extra += ['--status', args.status]
        route_role = getattr(args, 'role', '') or getattr(args, 'kind', '')
        if route_role:
            extra += ['--role', route_role]
        commands.append(planned_command(root, 'list-asset-locations', extra))
    elif intent == 'record_decision':
        if not title:
            add_missing(missing, 'decision title')
        if not args.body:
            add_missing(missing, 'decision body')
        if title and args.body:
            commands.append(planned_command(root, 'record-decision', ['--title', title, '--body', args.body]))
    elif intent == 'summarize_state':
        commands.append(planned_command(root, 'summarize-state'))
    elif intent == 'build_release':
        extra = []
        for rid in getattr(args, 'result_id', []) or []:
            extra += ['--result-id', rid]
        if args.release_id:
            extra += ['--release-id', args.release_id]
        if args.allow_candidate:
            extra.append('--allow-candidate')
        if args.apply:
            if args.approved:
                extra.append('--apply')
                extra.append('--approved')
                safety.append('Release apply requested with explicit approval.')
            else:
                add_missing(missing, 'approved release confirmation')
                safety.append('Release apply copies artifacts and records release state; rerun the route with --approved only after user approval.')
        else:
            safety.append('Release packaging defaults to dry-run; rerun with --apply after reviewing MANIFEST plan.')
        commands.append(planned_command(root, 'build-release', extra))
    elif intent == 'validate_release':
        if not args.release_id:
            add_missing(missing, 'release_id')
        else:
            commands.append(planned_command(root, 'validate-release', ['--release-id', args.release_id]))

    verification = [] if missing else route_verification(ctx, root, intent, args)
    return {
        'phrase': phrase,
        'intent': intent,
        'group': group,
        'matched_pattern': matched_pattern,
        'state': state,
        'missing': missing,
        'safety_gates': safety,
        'planned_commands': commands,
        'verification_commands': verification,
        'notes': notes,
        'policy': 'Router only resolves short triggers into deterministic CLI commands; it does not directly edit project files.',
    }


def command_route(args: argparse.Namespace, ctx: Any) -> int:
    root = Path(args.root).resolve()
    payload = build_route_plan(ctx, root, args)
    payload['ready'] = not payload.get('missing') and payload.get('intent') != 'unknown'
    ctx.print_json(payload)
    return 0
