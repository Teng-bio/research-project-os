#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from _schema import *  # shared schema/constants/templates for the CLI facade
from _paths import *  # project-local path helpers
from _project_io import *  # JSON/TSV/JSONL IO, pointers, events, locks, and shared utilities
from _assets import (
    command_adopt_external_asset,
    command_checksum_asset,
    command_externalize_asset,
    command_list_assets,
    command_list_asset_locations,
    command_plan_externalize_assets,
    command_refresh_assets,
    command_register_asset,
    command_show_asset,
    command_update_asset,
    command_verify_external_assets,
    refresh_asset_usage,
)  # asset registry, checksums, and asset usage command group
from _decision_handoff import (
    command_list_decisions,
    command_record_decision,
    command_summarize_state,
    command_update_handoff,
)  # decision journal, handoff, and state summary command group
from _project_branch import (
    branch_row,
    command_archive_branch,
    command_create_branch,
    command_init,
    command_install_adapters,
    command_list_branches,
    command_new_project,
    command_refresh_indexes,
    command_restore_journal,
    command_set_current_branch,
    command_show_branch,
    command_start,
    command_status,
    count_rows,
    current_branch,
    ensure_initialized,
    refresh_branch_index,
)  # project bootstrap, adapters, status/start, refresh, and branch command group
from _migration import command_migrate_branch_first  # flat -> branch-first adoption/migration command group
from _health import command_doctor, command_validate  # validate/doctor command group
from _hooks import (
    command_dispatch_hooks,
    command_list_hooks,
)  # default-disabled manual hooks dispatcher/reporting command group
from _recovery import command_plan_recovery  # report-only recovery/crash inspection planning command group
from _sessions import (
    SESSION_STATUSES,
    build_session_cleanup_plan,
    command_close_session,
    command_create_session,
    command_list_sessions,
    command_pause_session,
    command_plan_session_cleanup,
    command_resume_session,
    command_set_current_session,
    command_set_session_focus,
    command_show_session,
    session_summary_for_dashboard,
)  # sessionized runtime pointer command group
from _result_release import (
    command_accept_result,
    command_build_release,
    command_list_releases,
    command_list_results,
    command_promote_result,
    command_register_result,
    command_show_current,
    command_show_release,
    command_show_result,
    command_supersede_result,
    command_validate_release,
)  # result lifecycle and release packaging command group
from _task_run import (
    add_run_input,
    command_add_context,
    command_add_dependency,
    command_add_run_command,
    command_add_run_input,
    command_add_run_metric,
    command_add_run_output,
    command_add_run_parameter,
    command_capture_run_env,
    command_close_run,
    command_close_task,
    command_create_run,
    command_create_task,
    command_list_runs,
    command_list_tasks,
    command_remove_context,
    command_remove_dependency,
    command_set_current_run,
    command_set_current_task,
    command_show_run,
    command_show_task,
    command_update_run,
    command_update_task,
    command_update_task_stage,
    create_task_record,
    default_context_manifest,
    environment_snapshot,
    find_run_manifest,
    refresh_run_index,
    refresh_task_index,
    run_index_row,
    task_dir,
    task_index_row,
    task_json_path,
)  # task lifecycle and run provenance command group






























def command_writes(args: argparse.Namespace) -> bool:
    command = getattr(args, 'command', '')
    apply_gated = {'init', 'new-project', 'install-adapters', 'build-adapters', 'promote-result', 'build-release', 'migrate-branch-first'}
    if command in apply_gated:
        return bool(getattr(args, 'apply', False))
    if command == 'checksum-asset':
        return bool(getattr(args, 'update', False))
    if command == 'externalize-asset':
        return bool(getattr(args, 'apply', False))
    if command == 'adopt-external-asset':
        return bool(getattr(args, 'apply', False))
    if command == 'validate-release':
        return bool(getattr(args, 'record', False))
    if command == 'export-dashboard':
        return bool(getattr(args, 'apply', False))
    if command == 'dispatch-hooks':
        return bool(getattr(args, 'write_report', False))
    if command == 'plan-session-cleanup':
        return bool(getattr(args, 'write_report', False))
    if command == 'plan-recovery':
        return False
    if command == 'restore-journal':
        return bool(getattr(args, 'apply', False))
    write_commands = {
        'refresh-indexes', 'create-branch', 'set-current-branch', 'archive-branch',
        'create-session', 'set-current-session', 'set-session-focus', 'pause-session', 'resume-session', 'close-session',
        'create-task', 'set-current-task', 'update-task', 'update-task-stage', 'close-task', 'add-dependency', 'remove-dependency', 'add-context', 'remove-context',
        'create-run', 'set-current-run', 'update-run', 'close-run', 'add-run-input', 'add-run-command', 'add-run-output', 'add-run-metric',
        'add-run-parameter', 'capture-run-env',
        'register-result', 'accept-result', 'supersede-result',
        'register-asset', 'update-asset', 'refresh-assets',
        'record-decision', 'update-handoff',
    }
    return command in write_commands






from _router import command_route as router_command_route


def command_route(args: argparse.Namespace) -> int:
    return router_command_route(args, sys.modules[__name__])




















































from _export import command_export_dashboard as export_command_dashboard


def command_export_dashboard(args: argparse.Namespace) -> int:
    return export_command_dashboard(args, sys.modules[__name__])















































def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Operate a repository-local research-project-os harness')
    sub = parser.add_subparsers(dest='command', required=True)
    def add_root(p: argparse.ArgumentParser) -> None: p.add_argument('--root', default='.', help='Project root')
    def add_route_args(p: argparse.ArgumentParser) -> None:
        p.add_argument('phrase')
        p.add_argument('--title', default='')
        p.add_argument('--branch-id', default='')
        p.add_argument('--session-id', default='')
        p.add_argument('--task-id', default='')
        p.add_argument('--run-id', default='')
        p.add_argument('--result-id', action='append', default=[])
        p.add_argument('--asset-id', default='')
        p.add_argument('--release-id', default='')
        p.add_argument('--path', default='')
        p.add_argument('--to', default='')
        p.add_argument('--kind', default='')
        p.add_argument('--mode', default='')
        p.add_argument('--role', default='')
        p.add_argument('--threshold', default='500M')
        p.add_argument('--primary-root', default='')
        p.add_argument('--backup-root', default='')
        p.add_argument('--dest-subpath', default='')
        p.add_argument('--max-files', type=int, default=50)
        p.add_argument('--max-depth', type=int, default=0)
        p.add_argument('--event-index', type=int, default=0)
        p.add_argument('--event', default='')
        p.add_argument('--limit', type=int, default=1)
        p.add_argument('--min-age-days', type=int, default=0)
        p.add_argument('--write-report', action='store_true')
        p.add_argument('--output', default='')
        p.add_argument('--max-lock-age-seconds', type=int, default=300)
        p.add_argument('--max-tmp-files', type=int, default=200)
        p.add_argument('--include-current', action='store_true')
        p.add_argument('--stage', default='')
        p.add_argument('--status', default='')
        p.add_argument('--scope', choices=['all', 'project', 'branch'], default='all')
        p.add_argument('--audit', action=argparse.BooleanOptionalAction, default=True)
        p.add_argument('--notes', default='')
        p.add_argument('--body', default='')
        p.add_argument('--run-command', default='')
        p.add_argument('--metric-name', default='')
        p.add_argument('--metric-value', default='')
        p.add_argument('--param', action='append', default=[])
        p.add_argument('--depends-on-task', action='append', default=[])
        p.add_argument('--depends-on-result', action='append', default=[])
        p.add_argument('--source-url', default='')
        p.add_argument('--replaced-by', default='')
        p.add_argument('--old-path', action='append', default=[])
        p.add_argument('--backup-path', action='append', default=[])
        p.add_argument('--mirror-path', action='append', default=[])
        p.add_argument('--archive-path', action='append', default=[])
        p.add_argument('--freeze-file', default='docs/pip-freeze.txt')
        p.add_argument('--pip-freeze', action='store_true')
        p.add_argument('--allow-candidate', action='store_true')
        p.add_argument('--set-current', action='store_true')
        p.add_argument('--replace', action='store_true')
        p.add_argument('--apply', action='store_true')
        p.add_argument('--approved', action='store_true')

    p = sub.add_parser('init', help='Create .project_os scaffold; dry-run unless --apply'); add_root(p); p.add_argument('--title', default='Untitled project'); p.add_argument('--profile', default='research'); p.add_argument('--apply', action='store_true'); p.set_defaults(func=command_init)
    p = sub.add_parser('new-project', help='Create a new project workflow skeleton; dry-run unless --apply'); add_root(p); p.add_argument('--title', default='Untitled project'); p.add_argument('--profile', default='research'); p.add_argument('--platforms', nargs='*', default=['codex']); p.add_argument('--apply', action='store_true'); p.add_argument('--install-adapters', action=argparse.BooleanOptionalAction, default=True); p.add_argument('--bootstrap-task', action=argparse.BooleanOptionalAction, default=True); p.add_argument('--bootstrap-title', default=''); p.set_defaults(func=command_new_project)
    p = sub.add_parser('start'); add_root(p); p.set_defaults(func=command_start)
    p = sub.add_parser('status'); add_root(p); p.set_defaults(func=command_status)
    p = sub.add_parser('route', help='Resolve a short natural-language trigger into deterministic project_os.py commands without executing them'); add_root(p); add_route_args(p); p.set_defaults(func=command_route)
    p = sub.add_parser('explain-trigger', help='Alias for route; shows how a short trigger would be handled'); add_root(p); add_route_args(p); p.set_defaults(func=command_route)
    p = sub.add_parser('doctor'); add_root(p); p.add_argument('--json', action='store_true', help='Accepted for compatibility; output is always JSON'); p.add_argument('--repair-plan', action='store_true'); p.set_defaults(func=command_doctor)
    p = sub.add_parser('validate'); add_root(p); p.set_defaults(func=command_validate)
    p = sub.add_parser('refresh-indexes'); add_root(p); p.set_defaults(func=command_refresh_indexes)
    p = sub.add_parser('restore-journal', help='Create a missing .project_os/journals/events.jsonl; dry-run unless --apply --approved'); add_root(p); p.add_argument('--apply', action='store_true'); p.add_argument('--approved', action='store_true'); p.add_argument('--reason', default=''); p.set_defaults(func=command_restore_journal)
    p = sub.add_parser('install-adapters'); add_root(p); p.add_argument('--platforms', nargs='*', default=['codex']); p.add_argument('--apply', action='store_true'); p.set_defaults(func=command_install_adapters)
    p = sub.add_parser('build-adapters'); add_root(p); p.add_argument('--platforms', nargs='*', default=['codex']); p.add_argument('--apply', action='store_true'); p.set_defaults(func=command_install_adapters)

    p = sub.add_parser('create-branch'); add_root(p); p.add_argument('--title', required=True); p.add_argument('--branch-id', default=''); p.add_argument('--parent-branch-id', default=''); p.add_argument('--git-branch', default=''); p.add_argument('--notes', default=''); p.add_argument('--set-current', action='store_true'); p.set_defaults(func=command_create_branch)
    p = sub.add_parser('set-current-branch'); add_root(p); p.add_argument('--branch-id', required=True); p.set_defaults(func=command_set_current_branch)
    p = sub.add_parser('list-branches'); add_root(p); p.add_argument('--status', default=''); p.set_defaults(func=command_list_branches)
    p = sub.add_parser('show-branch'); add_root(p); p.add_argument('--branch-id', required=True); p.set_defaults(func=command_show_branch)
    p = sub.add_parser('archive-branch'); add_root(p); p.add_argument('--branch-id', required=True); p.add_argument('--status', choices=['archived', 'abandoned', 'completed'], default='archived'); p.add_argument('--notes', default=''); p.set_defaults(func=command_archive_branch)

    p = sub.add_parser('create-session', help='Create a named runtime focus under .project_os/runtime/sessions/<session_id>'); add_root(p); p.add_argument('--session-id', required=True); p.add_argument('--title', default=''); p.add_argument('--branch-id', default=''); p.add_argument('--task-id', default=''); p.add_argument('--run-id', default=''); p.add_argument('--no-task', action='store_true'); p.add_argument('--no-run', action='store_true'); p.add_argument('--set-current', action='store_true'); p.add_argument('--replace', action='store_true'); p.add_argument('--notes', default=''); p.set_defaults(func=command_create_session)
    p = sub.add_parser('set-current-session', help='Switch active runtime focus to a named session, or --clear to return to global pointers'); add_root(p); p.add_argument('--session-id', default=''); p.add_argument('--clear', action='store_true'); p.set_defaults(func=command_set_current_session)
    p = sub.add_parser('list-sessions'); add_root(p); p.add_argument('--status', default=''); p.set_defaults(func=command_list_sessions)
    p = sub.add_parser('show-session'); add_root(p); p.add_argument('--session-id', default=''); p.set_defaults(func=command_show_session)
    p = sub.add_parser('set-session-focus'); add_root(p); p.add_argument('--session-id', required=True); p.add_argument('--branch-id', default=''); p.add_argument('--task-id', default=''); p.add_argument('--run-id', default=''); p.add_argument('--clear-task', action='store_true'); p.add_argument('--clear-run', action='store_true'); p.add_argument('--set-current', action='store_true'); p.add_argument('--notes', default=''); p.set_defaults(func=command_set_session_focus)
    p = sub.add_parser('pause-session', help='Pause a named runtime session and clear it if it is current'); add_root(p); p.add_argument('--session-id', required=True); p.add_argument('--notes', default=''); p.set_defaults(func=command_pause_session)
    p = sub.add_parser('resume-session', help='Resume a paused runtime session; use --set-current to activate it'); add_root(p); p.add_argument('--session-id', required=True); p.add_argument('--set-current', action='store_true'); p.add_argument('--notes', default=''); p.set_defaults(func=command_resume_session)
    p = sub.add_parser('close-session'); add_root(p); p.add_argument('--session-id', required=True); p.add_argument('--notes', default=''); p.set_defaults(func=command_close_session)
    p = sub.add_parser('plan-session-cleanup', help='Report-only session archive/cleanup candidates; never deletes or moves session state'); add_root(p); p.add_argument('--status', action='append', choices=sorted(SESSION_STATUSES), default=[]); p.add_argument('--min-age-days', type=int, default=0); p.add_argument('--include-current', action='store_true'); p.add_argument('--write-report', action='store_true'); p.add_argument('--output', default='.project_os/exports/session_cleanup'); p.set_defaults(func=command_plan_session_cleanup)
    p = sub.add_parser('plan-recovery', help='Report-only crash/recovery inspection; never replays, rolls back, deletes, or removes locks'); add_root(p); p.add_argument('--max-lock-age-seconds', type=int, default=300); p.add_argument('--max-tmp-files', type=int, default=200); p.add_argument('--write-report', action='store_true'); p.add_argument('--output', default='.project_os/exports/recovery'); p.set_defaults(func=command_plan_recovery)

    p = sub.add_parser('create-task'); add_root(p); p.add_argument('--title', required=True); p.add_argument('--kind', default='analysis'); p.add_argument('--task-id', default=''); p.add_argument('--branch-id', default=''); p.add_argument('--parent-task-id', default=None); p.add_argument('--owner', default=''); p.add_argument('--stage', default='Intake'); p.add_argument('--priority', default='normal'); p.add_argument('--notes', default=''); p.add_argument('--set-current', action='store_true'); p.set_defaults(func=command_create_task)
    p = sub.add_parser('set-current-task'); add_root(p); p.add_argument('--task-id', required=True); p.set_defaults(func=command_set_current_task)
    p = sub.add_parser('list-tasks'); add_root(p); p.add_argument('--branch-id', default=''); p.add_argument('--status', default=''); p.add_argument('--stage', default=''); p.set_defaults(func=command_list_tasks)
    p = sub.add_parser('show-task'); add_root(p); p.add_argument('--task-id', required=True); p.add_argument('--branch-id', default=''); p.set_defaults(func=command_show_task)
    p = sub.add_parser('update-task'); add_root(p); p.add_argument('--task-id', required=True); p.add_argument('--branch-id', default=''); p.add_argument('--title', default=''); p.add_argument('--kind', default=''); p.add_argument('--owner', default=None); p.add_argument('--priority', default=None); p.add_argument('--status', default=''); p.add_argument('--notes', default=''); p.set_defaults(func=command_update_task)
    p = sub.add_parser('update-task-stage'); add_root(p); p.add_argument('--task-id', required=True); p.add_argument('--stage', required=True, choices=sorted(STAGES)); p.add_argument('--branch-id', default=''); p.add_argument('--status', default=''); p.add_argument('--notes', default=''); p.set_defaults(func=command_update_task_stage)
    p = sub.add_parser('close-task'); add_root(p); p.add_argument('--task-id', required=True); p.add_argument('--status', required=True, choices=sorted(TASK_STATUSES)); p.add_argument('--branch-id', default=''); p.add_argument('--notes', default=''); p.set_defaults(func=command_close_task)
    p = sub.add_parser('add-dependency'); add_root(p); p.add_argument('--task-id', required=True); p.add_argument('--branch-id', default=''); p.add_argument('--depends-on-task', action='append', default=[]); p.add_argument('--depends-on-result', action='append', default=[]); p.set_defaults(func=command_add_dependency)
    p = sub.add_parser('remove-dependency'); add_root(p); p.add_argument('--task-id', required=True); p.add_argument('--branch-id', default=''); p.add_argument('--depends-on-task', action='append', default=[]); p.add_argument('--depends-on-result', action='append', default=[]); p.set_defaults(func=command_remove_dependency)
    p = sub.add_parser('add-context'); add_root(p); p.add_argument('--task-id', required=True); p.add_argument('--path', required=True); p.add_argument('--type', default='reference'); p.add_argument('--purpose', required=True); p.add_argument('--required', action='store_true'); p.add_argument('--branch-id', default=''); p.set_defaults(func=command_add_context)
    p = sub.add_parser('remove-context'); add_root(p); p.add_argument('--task-id', required=True); p.add_argument('--path', required=True); p.add_argument('--branch-id', default=''); p.set_defaults(func=command_remove_context)

    p = sub.add_parser('create-run'); add_root(p); p.add_argument('--task-id', required=True); p.add_argument('--slug', required=True); p.add_argument('--run-id', default=''); p.add_argument('--run-root', default='runs'); p.add_argument('--notes', default=''); p.set_defaults(func=command_create_run)
    p = sub.add_parser('set-current-run'); add_root(p); p.add_argument('--run-id', required=True); p.set_defaults(func=command_set_current_run)
    p = sub.add_parser('update-run'); add_root(p); p.add_argument('--run-id', required=True); p.add_argument('--branch-id', default=''); p.add_argument('--status', default='', choices=[''] + sorted(RUN_STATUSES)); p.add_argument('--result-status', default='', choices=[''] + sorted(RESULT_STATUSES)); p.add_argument('--notes', default=''); p.set_defaults(func=command_update_run)
    p = sub.add_parser('close-run'); add_root(p); p.add_argument('--run-id', required=True); p.add_argument('--status', required=True, choices=sorted(RUN_STATUSES)); p.add_argument('--notes', default=''); p.set_defaults(func=command_close_run)
    p = sub.add_parser('list-runs'); add_root(p); p.add_argument('--branch-id', default=''); p.add_argument('--task-id', default=''); p.add_argument('--status', default=''); p.set_defaults(func=command_list_runs)
    p = sub.add_parser('show-run'); add_root(p); p.add_argument('--run-id', required=True); p.add_argument('--branch-id', default=''); p.set_defaults(func=command_show_run)
    p = sub.add_parser('add-run-input'); add_root(p); p.add_argument('--run-id', required=True); p.add_argument('--asset-id', default=''); p.add_argument('--path', default=''); p.add_argument('--name', default=''); p.add_argument('--usage-kind', default='input'); p.add_argument('--notes', default=''); p.set_defaults(func=command_add_run_input)
    p = sub.add_parser('add-run-command'); add_root(p); p.add_argument('--run-id', required=True); p.add_argument('--command', required=True); p.add_argument('--cwd', default=''); p.add_argument('--exit-code', type=int, default=None); p.add_argument('--notes', default=''); p.set_defaults(func=command_add_run_command)
    p = sub.add_parser('add-run-output'); add_root(p); p.add_argument('--run-id', required=True); p.add_argument('--path', required=True); p.add_argument('--kind', default='artifact'); p.add_argument('--result-id', default=''); p.add_argument('--asset-id', default=''); p.add_argument('--notes', default=''); p.set_defaults(func=command_add_run_output)
    p = sub.add_parser('add-run-metric'); add_root(p); p.add_argument('--run-id', required=True); p.add_argument('--name', required=True); p.add_argument('--value', required=True); p.add_argument('--unit', default=''); p.add_argument('--notes', default=''); p.set_defaults(func=command_add_run_metric)
    p = sub.add_parser('add-run-parameter'); add_root(p); p.add_argument('--run-id', required=True); p.add_argument('--param', action='append', default=[], required=True, help='key=value; value may be JSON'); p.set_defaults(func=command_add_run_parameter)
    p = sub.add_parser('capture-run-env'); add_root(p); p.add_argument('--run-id', required=True); p.add_argument('--pip-freeze', action='store_true'); p.add_argument('--freeze-file', default='docs/pip-freeze.txt'); p.set_defaults(func=command_capture_run_env)

    p = sub.add_parser('register-result'); add_root(p); p.add_argument('--run-id', required=True); p.add_argument('--path', required=True); p.add_argument('--status', default='candidate'); p.add_argument('--type', default='artifact'); p.add_argument('--title', default=''); p.add_argument('--result-id', default=''); p.add_argument('--notes', default=''); p.add_argument('--allow-missing', action='store_true'); p.add_argument('--approved', action='store_true'); p.set_defaults(func=command_register_result)
    p = sub.add_parser('accept-result'); add_root(p); p.add_argument('--result-id', required=True); p.add_argument('--approved', action='store_true'); p.add_argument('--notes', default=''); p.set_defaults(func=command_accept_result)
    p = sub.add_parser('promote-result'); add_root(p); p.add_argument('--result-id', required=True); p.add_argument('--to', required=True); p.add_argument('--apply', action='store_true'); p.add_argument('--approved', action='store_true'); p.add_argument('--replace', action='store_true'); p.set_defaults(func=command_promote_result)
    p = sub.add_parser('supersede-result'); add_root(p); p.add_argument('--result-id', required=True); p.add_argument('--replaced-by', default=''); p.add_argument('--approved', action='store_true'); p.add_argument('--notes', default=''); p.set_defaults(func=command_supersede_result)
    p = sub.add_parser('show-current'); add_root(p); p.add_argument('--branch-id', default=''); p.add_argument('--project-only', action='store_true'); p.add_argument('--scope', choices=['all', 'project', 'branch'], default='all'); p.add_argument('--audit', action='store_true'); p.set_defaults(func=command_show_current)
    p = sub.add_parser('list-results'); add_root(p); p.add_argument('--branch-id', default=''); p.add_argument('--task-id', default=''); p.add_argument('--status', default=''); p.set_defaults(func=command_list_results)
    p = sub.add_parser('show-result'); add_root(p); p.add_argument('--result-id', required=True); p.set_defaults(func=command_show_result)
    p = sub.add_parser('register-asset'); add_root(p); p.add_argument('--path', default=''); p.add_argument('--kind', default='data'); p.add_argument('--asset-id', default=''); p.add_argument('--version', default=''); p.add_argument('--source-url', default=''); p.add_argument('--source-note', default=''); p.add_argument('--immutable', action=argparse.BooleanOptionalAction, default=None); p.add_argument('--status', default='active', choices=sorted(ASSET_STATUSES)); p.add_argument('--checksum', default=''); p.add_argument('--no-checksum', action='store_true'); p.add_argument('--allow-missing', action='store_true'); p.add_argument('--notes', default=''); p.add_argument('--branch-id', default=''); p.add_argument('--task-id', default=''); p.add_argument('--run-id', default=''); p.add_argument('--usage-kind', default='input'); p.add_argument('--name', default=''); p.set_defaults(func=command_register_asset)
    p = sub.add_parser('list-assets'); add_root(p); p.add_argument('--kind', default=''); p.add_argument('--status', default=''); p.set_defaults(func=command_list_assets)
    p = sub.add_parser('show-asset'); add_root(p); p.add_argument('--asset-id', required=True); p.set_defaults(func=command_show_asset)
    p = sub.add_parser('list-asset-locations'); add_root(p); p.add_argument('--asset-id', default=''); p.add_argument('--role', default=''); p.add_argument('--status', default=''); p.set_defaults(func=command_list_asset_locations)
    p = sub.add_parser('update-asset'); add_root(p); p.add_argument('--asset-id', required=True); p.add_argument('--kind', default=None); p.add_argument('--path', default=None); p.add_argument('--version', default=None); p.add_argument('--source-url', default=None); p.add_argument('--source-note', default=None); p.add_argument('--immutable', action=argparse.BooleanOptionalAction, default=None); p.add_argument('--status', default=''); p.add_argument('--checksum', default=None); p.add_argument('--rechecksum', action='store_true'); p.add_argument('--notes', default=None); p.set_defaults(func=command_update_asset)
    p = sub.add_parser('checksum-asset'); add_root(p); p.add_argument('--asset-id', default=''); p.add_argument('--path', default=''); p.add_argument('--update', action='store_true'); p.set_defaults(func=command_checksum_asset)
    p = sub.add_parser('plan-externalize-assets'); add_root(p); p.add_argument('--threshold', default='500M'); p.add_argument('--primary-root', default=''); p.add_argument('--backup-root', default=''); p.add_argument('--mode', choices=['copy', 'move'], default='copy'); p.add_argument('--max-files', type=int, default=50); p.add_argument('--max-depth', type=int, default=0); p.add_argument('--write-report', action='store_true'); p.add_argument('--output', default='.project_os/exports/asset_externalization'); p.set_defaults(func=command_plan_externalize_assets)
    p = sub.add_parser('externalize-asset'); add_root(p); p.add_argument('--path', required=True); p.add_argument('--asset-id', default=''); p.add_argument('--kind', default='data'); p.add_argument('--primary-root', default=''); p.add_argument('--backup-root', default=''); p.add_argument('--dest-subpath', default=''); p.add_argument('--mode', choices=['copy', 'move'], default='copy'); p.add_argument('--notes', default=''); p.add_argument('--branch-id', default=''); p.add_argument('--task-id', default=''); p.add_argument('--run-id', default=''); p.add_argument('--usage-kind', default='input'); p.add_argument('--name', default=''); p.add_argument('--write-report', action='store_true'); p.add_argument('--output', default='.project_os/exports/asset_externalization'); p.add_argument('--apply', action='store_true'); p.add_argument('--approved', action='store_true'); p.set_defaults(func=command_externalize_asset)
    p = sub.add_parser('adopt-external-asset'); add_root(p); p.add_argument('--path', required=True); p.add_argument('--asset-id', default=''); p.add_argument('--kind', default='data'); p.add_argument('--old-path', action='append', default=[]); p.add_argument('--backup-path', action='append', default=[]); p.add_argument('--mirror-path', action='append', default=[]); p.add_argument('--archive-path', action='append', default=[]); p.add_argument('--notes', default=''); p.add_argument('--branch-id', default=''); p.add_argument('--task-id', default=''); p.add_argument('--run-id', default=''); p.add_argument('--usage-kind', default='input'); p.add_argument('--name', default=''); p.add_argument('--write-report', action='store_true'); p.add_argument('--output', default='.project_os/exports/asset_externalization'); p.add_argument('--apply', action='store_true'); p.add_argument('--approved', action='store_true'); p.set_defaults(func=command_adopt_external_asset)
    p = sub.add_parser('verify-external-assets'); add_root(p); p.add_argument('--asset-id', default=''); p.add_argument('--checksum', action='store_true'); p.set_defaults(func=command_verify_external_assets)
    p = sub.add_parser('refresh-assets'); add_root(p); p.set_defaults(func=command_refresh_assets)
    p = sub.add_parser('record-decision'); add_root(p); p.add_argument('--title', required=True); p.add_argument('--body', default=''); p.add_argument('--body-file', default=''); p.add_argument('--decision-id', default=''); p.add_argument('--scope', choices=['project', 'branch', 'task'], default='project'); p.add_argument('--branch-id', default=''); p.add_argument('--task-id', default=''); p.add_argument('--status', default='accepted'); p.add_argument('--notes', default=''); p.set_defaults(func=command_record_decision)
    p = sub.add_parser('list-decisions'); add_root(p); p.add_argument('--scope', default=''); p.add_argument('--branch-id', default=''); p.add_argument('--task-id', default=''); p.add_argument('--status', default=''); p.set_defaults(func=command_list_decisions)
    p = sub.add_parser('update-handoff'); add_root(p); p.add_argument('--scope', choices=['project', 'branch', 'task'], default='project'); p.add_argument('--message', default=''); p.add_argument('--message-file', default=''); p.add_argument('--branch-id', default=''); p.add_argument('--task-id', default=''); p.add_argument('--replace', action='store_true'); p.set_defaults(func=command_update_handoff)
    p = sub.add_parser('summarize-state'); add_root(p); p.add_argument('--recent-events', type=int, default=5); p.set_defaults(func=command_summarize_state)
    p = sub.add_parser('export-dashboard'); add_root(p); p.add_argument('--output', default='.project_os/exports'); p.add_argument('--recent-events', type=int, default=20); p.add_argument('--sqlite', action='store_true'); p.add_argument('--apply', action='store_true'); p.set_defaults(func=command_export_dashboard)
    p = sub.add_parser('list-hooks', help='List default-disabled hook handler reports and policy'); add_root(p); p.set_defaults(func=command_list_hooks)
    p = sub.add_parser('dispatch-hooks', help='Manually dispatch read-only hook reports from events.jsonl; does not auto-run hooks'); add_root(p); p.add_argument('--event-index', type=int, default=0); p.add_argument('--event', default=''); p.add_argument('--limit', type=int, default=1); p.add_argument('--kind', action='append', choices=['session_summary', 'reminder', 'opt_in_maintenance', 'guard'], default=[]); p.add_argument('--write-report', action='store_true'); p.add_argument('--output', default='.project_os/exports/hooks'); p.set_defaults(func=command_dispatch_hooks)
    p = sub.add_parser('build-release'); add_root(p); p.add_argument('--release-id', default=''); p.add_argument('--result-id', action='append', default=[]); p.add_argument('--status', default='built', choices=sorted(RELEASE_STATUSES)); p.add_argument('--allow-candidate', action='store_true'); p.add_argument('--apply', action='store_true'); p.add_argument('--approved', action='store_true'); p.add_argument('--replace', action='store_true'); p.add_argument('--notes', default=''); p.set_defaults(func=command_build_release)
    p = sub.add_parser('list-releases'); add_root(p); p.add_argument('--status', default=''); p.set_defaults(func=command_list_releases)
    p = sub.add_parser('show-release'); add_root(p); p.add_argument('--release-id', required=True); p.set_defaults(func=command_show_release)
    p = sub.add_parser('validate-release'); add_root(p); p.add_argument('--release-id', required=True); p.add_argument('--record', action='store_true'); p.set_defaults(func=command_validate_release)
    p = sub.add_parser('migrate-branch-first'); add_root(p); p.add_argument('--branch-id', default=DEFAULT_BRANCH); p.add_argument('--apply', action='store_true'); p.add_argument('--mode', choices=['move', 'copy'], default='move'); p.add_argument('--replace', action='store_true'); p.add_argument('--preserve-manifest-branches', action='store_true'); p.set_defaults(func=command_migrate_branch_first)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(); args = parser.parse_args(argv)
    try:
        if command_writes(args):
            root = Path(getattr(args, 'root', '.')).resolve()
            with harness_lock(root):
                return args.func(args)
        return args.func(args)
    except ProjectOSError as exc:
        print_json({'error': str(exc)}); return 2


if __name__ == '__main__':
    raise SystemExit(main())
