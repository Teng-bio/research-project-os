from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

from _paths import project_os, relpath
from _project_io import (
    ProjectOSError,
    current_session,
    events_path,
    focus_payload,
    now_iso,
    print_json,
    read_jsonl,
    timestamp,
    write_json,
)


HOOK_KINDS = ['session_summary', 'reminder', 'opt_in_maintenance', 'guard']
DEFAULT_DISPATCH_KINDS = ['session_summary', 'reminder', 'opt_in_maintenance']


def project_os_command(root: Path, subcommand: str, extra: list[str] | None = None) -> str:
    script = Path(__file__).resolve().parent / 'project_os.py'
    argv = [sys.executable, script.as_posix(), subcommand, '--root', root.as_posix()]
    if extra:
        argv.extend([str(item) for item in extra])
    return ' '.join(shlex.quote(part) for part in argv)


def parse_hooks_config(root: Path) -> dict[str, Any]:
    path = project_os(root) / 'config.yaml'
    config: dict[str, Any] = {
        'path': relpath(root, path),
        'exists': path.exists(),
        'enabled': False,
        'mode': 'disabled',
        'dispatcher': 'none',
        'event_source': '.project_os/journals/events.jsonl',
        'allowed_kinds': [],
        'policy': {},
    }
    if not path.exists():
        return config

    in_hooks = False
    current_list = ''
    in_policy = False
    for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if re.match(r'^hooks:\s*$', raw):
            in_hooks = True
            in_policy = False
            current_list = ''
            continue
        if not in_hooks:
            continue
        if raw and not raw.startswith(' '):
            break
        stripped = raw.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('- ') and current_list == 'allowed_kinds':
            config['allowed_kinds'].append(stripped[2:].strip())
            continue
        key_value = re.match(r'^([A-Za-z0-9_]+):\s*(.*)$', stripped)
        if not key_value:
            continue
        key, value = key_value.group(1), key_value.group(2).strip()
        if key == 'policy':
            in_policy = True
            current_list = ''
            continue
        if key == 'allowed_kinds':
            current_list = 'allowed_kinds'
            in_policy = False
            continue
        if in_policy:
            config['policy'][key] = parse_scalar(value)
        else:
            config[key] = parse_scalar(value)
            current_list = ''
    return config


def parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {'true', 'false'}:
        return lowered == 'true'
    if lowered in {'null', 'none'}:
        return None
    return value.strip("'\"")


def event_label(event: dict[str, Any]) -> str:
    return str(event.get('event') or '(unknown)')


def event_brief(event: dict[str, Any]) -> dict[str, str]:
    detail = event.get('detail', {}) if isinstance(event.get('detail'), dict) else {}
    return {
        'event': str(event.get('event', '')),
        'ts': str(event.get('ts', '')),
        'branch_id': str(event.get('branch_id') or detail.get('branch_id') or ''),
        'task_id': str(event.get('task_id') or detail.get('task_id') or ''),
        'run_id': str(event.get('run_id') or detail.get('run_id') or ''),
        'result_id': str(event.get('result_id') or detail.get('result_id') or ''),
        'asset_id': str(detail.get('asset_id') or ''),
        'release_id': str(detail.get('release_id') or ''),
        'session_id': str(detail.get('session_id') or detail.get('current_session') or ''),
    }


def select_events(root: Path, args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path = events_path(root)
    rows = read_jsonl(path) if path.exists() else []
    malformed = [
        {'line_no': idx, 'raw': str(event.get('raw', ''))}
        for idx, event in enumerate(rows, start=1)
        if event.get('_error')
    ]
    indexed = [
        {'line_no': idx, **event}
        for idx, event in enumerate(rows, start=1)
        if not event.get('_error')
    ]
    if args.event_index:
        selected = [event for event in indexed if int(event.get('line_no', 0)) == args.event_index]
        if not selected:
            raise ProjectOSError(f'No event at line/index: {args.event_index}')
        return selected, malformed
    if args.event:
        indexed = [event for event in indexed if event.get('event') == args.event]
    limit = max(1, int(args.limit or 1))
    return indexed[-limit:], malformed


def hook_report(kind: str, event: dict[str, Any], *, status: str, message: str, suggested_commands: list[str] | None = None, notes: list[str] | None = None, risk: str = 'low') -> dict[str, Any]:
    return {
        'hook_id': f'{kind}:{event_label(event)}',
        'kind': kind,
        'event': event_label(event),
        'event_line_no': event.get('line_no', ''),
        'status': status,
        'risk': risk,
        'message': message,
        'suggested_commands': suggested_commands or [],
        'notes': notes or [],
        'policy': 'Manual hook dispatcher report only; handlers must not edit canonical state directly.',
    }


def session_summary_report(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    focus = focus_payload(root)
    session_id = current_session(root)
    commands = [
        project_os_command(root, 'status'),
        project_os_command(root, 'start'),
    ]
    if session_id:
        commands.append(project_os_command(root, 'show-session', ['--session-id', session_id]))
    message = (
        f"Focus source={focus.get('source', 'global')}; "
        f"session={focus.get('session_id', '') or '(none)'}; "
        f"branch={focus.get('current_branch', '') or '(none)'}; "
        f"task={focus.get('current_task', '') or '(none)'}; "
        f"run={focus.get('current_run', '') or '(none)'}."
    )
    report = hook_report('session_summary', event, status='ok', message=message, suggested_commands=commands)
    report['focus'] = focus
    return report


def reminder_report(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    event_name = event_label(event)
    brief = event_brief(event)
    commands: list[str] = []
    notes: list[str] = []
    message = 'No specific reminder for this event; run status/doctor if unsure.'

    if event_name in {'project.initialized', 'project.adopted', 'journal.restored'}:
        message = 'Project harness changed; verify adapters, current focus, and health.'
        commands = [
            project_os_command(root, 'status'),
            project_os_command(root, 'doctor'),
            project_os_command(root, 'install-adapters', ['--platforms', 'codex', 'claude']),
        ]
        if event_name == 'journal.restored':
            message = 'Event journal was restored; verify health and review any remaining provenance coverage warnings.'
            commands = [
                project_os_command(root, 'validate'),
                project_os_command(root, 'doctor', ['--repair-plan']),
                project_os_command(root, 'summarize-state'),
            ]
    elif event_name in {'branch.created', 'branch.changed', 'branch.archived'}:
        message = 'Branch lifecycle changed; verify current focus and branch health.'
        commands = [project_os_command(root, 'list-branches'), project_os_command(root, 'status'), project_os_command(root, 'doctor')]
    elif event_name in {'task.created', 'task.changed', 'task.closed'}:
        message = 'Task lifecycle changed; review task context and next run state.'
        task_id = brief.get('task_id')
        commands = [project_os_command(root, 'show-task', ['--task-id', task_id])] if task_id else [project_os_command(root, 'list-tasks')]
        commands.append(project_os_command(root, 'doctor'))
    elif event_name in {'run.created', 'run.updated'}:
        message = 'Run provenance changed; ensure inputs, commands, parameters, environment, and outputs are captured.'
        run_id = brief.get('run_id')
        if run_id:
            commands = [
                project_os_command(root, 'show-run', ['--run-id', run_id]),
                project_os_command(root, 'capture-run-env', ['--run-id', run_id]),
            ]
        else:
            commands = [project_os_command(root, 'list-runs')]
    elif event_name == 'run.closed':
        message = 'Run was closed; register candidate results or refresh derived views if outputs changed.'
        run_id = brief.get('run_id')
        commands = [project_os_command(root, 'show-run', ['--run-id', run_id])] if run_id else [project_os_command(root, 'list-runs')]
        commands.extend([project_os_command(root, 'refresh-indexes'), project_os_command(root, 'doctor')])
    elif event_name in {'result.registered', 'result.accepted', 'result.promoted', 'result.superseded'}:
        message = 'Result lifecycle changed; review result/current views and promotion audit.'
        result_id = brief.get('result_id')
        commands = [project_os_command(root, 'show-result', ['--result-id', result_id])] if result_id else [project_os_command(root, 'list-results')]
        commands.extend([project_os_command(root, 'show-current', ['--scope', 'all', '--audit']), project_os_command(root, 'refresh-indexes')])
    elif event_name in {'asset.registered', 'asset.updated'}:
        message = 'Asset registry changed; refresh asset usage and check health.'
        commands = [project_os_command(root, 'refresh-assets'), project_os_command(root, 'doctor')]
    elif event_name in {'release.created', 'release.validated'}:
        message = 'Release lifecycle changed; validate release package and health.'
        release_id = brief.get('release_id')
        commands = [project_os_command(root, 'validate-release', ['--release-id', release_id])] if release_id else [project_os_command(root, 'list-releases')]
        commands.append(project_os_command(root, 'doctor'))
    elif event_name in {'session.created', 'session.changed', 'session.paused', 'session.resumed', 'session.closed'}:
        message = 'Session focus changed; verify active focus before continuing work.'
        session_id = brief.get('session_id')
        commands = [project_os_command(root, 'show-session', ['--session-id', session_id])] if session_id else [project_os_command(root, 'list-sessions')]
        commands.append(project_os_command(root, 'start'))
        if event_name == 'session.closed':
            commands.append(project_os_command(root, 'plan-session-cleanup', ['--status', 'closed']))
            notes.append('Session cleanup planning is report-only; it does not delete or move session directories.')
    elif event_name in {'decision.recorded', 'handoff.updated', 'state.updated'}:
        message = 'Handoff or decision state changed; summarize state before stopping or resuming.'
        commands = [project_os_command(root, 'summarize-state'), project_os_command(root, 'doctor')]
    elif event_name == 'export.created':
        message = 'Generated export changed; remember exports are derived views, not canonical state.'
        commands = [project_os_command(root, 'status')]
        notes.append('Do not edit dashboard/export files as source of truth.')

    return hook_report('reminder', event, status='ok', message=message, suggested_commands=commands, notes=notes)


def maintenance_report(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    event_name = event_label(event)
    commands = [
        project_os_command(root, 'doctor'),
        project_os_command(root, 'validate'),
    ]
    if event_name in {'run.closed', 'result.registered', 'result.accepted', 'result.promoted', 'asset.registered', 'asset.updated', 'release.created'}:
        commands.insert(0, project_os_command(root, 'refresh-indexes'))
    return hook_report(
        'opt_in_maintenance',
        event,
        status='planned',
        risk='medium',
        message='Maintenance hook is opt-in. This dispatcher reports commands but does not execute them.',
        suggested_commands=commands,
        notes=['Run the suggested commands manually, or implement a future opt-in executor that calls project_os.py commands only.'],
    )


def guard_report(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    event_name = event_label(event)
    commands = [project_os_command(root, 'doctor')]
    if event_name.startswith('result.'):
        commands.insert(0, project_os_command(root, 'show-current', ['--scope', 'all', '--audit']))
    elif event_name.startswith('release.'):
        commands.insert(0, project_os_command(root, 'list-releases'))
    return hook_report(
        'guard',
        event,
        status='skipped',
        risk='high',
        message='Guard hooks are preflight checks and remain disabled. Existing CLI approval gates are still authoritative.',
        suggested_commands=commands,
        notes=['Future guard hooks must be explicit opt-in and must not bypass --approved / --apply gates.'],
    )


def run_hook_kind(root: Path, event: dict[str, Any], kind: str) -> dict[str, Any]:
    if kind == 'session_summary':
        return session_summary_report(root, event)
    if kind == 'reminder':
        return reminder_report(root, event)
    if kind == 'opt_in_maintenance':
        return maintenance_report(root, event)
    if kind == 'guard':
        return guard_report(root, event)
    return hook_report(kind, event, status='skipped', risk='unknown', message=f'Unknown hook kind: {kind}')


def command_list_hooks(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    config = parse_hooks_config(root)
    handlers = [
        {
            'kind': 'session_summary',
            'risk': 'low',
            'implemented': True,
            'default_manual': True,
            'writes_canonical_state': False,
        },
        {
            'kind': 'reminder',
            'risk': 'low',
            'implemented': True,
            'default_manual': True,
            'writes_canonical_state': False,
        },
        {
            'kind': 'opt_in_maintenance',
            'risk': 'medium',
            'implemented': True,
            'default_manual': True,
            'writes_canonical_state': False,
            'executes_commands': False,
        },
        {
            'kind': 'guard',
            'risk': 'high',
            'implemented': 'report_only',
            'default_manual': False,
            'writes_canonical_state': False,
            'blocks_operations': False,
        },
    ]
    print_json({
        'root': root.as_posix(),
        'active_dispatcher_enabled': False,
        'manual_dispatcher_available': True,
        'config': config,
        'handlers': handlers,
        'policy': {
            'core_harness_works_without_hooks': True,
            'event_source': relpath(root, events_path(root)),
            'handlers_must_call_cli': True,
            'handlers_must_not_write_canonical_state_directly': True,
            'guard_hooks_require_future_explicit_opt_in': True,
        },
        'example': project_os_command(root, 'dispatch-hooks', ['--limit', '1']),
    })
    return 0


def command_dispatch_hooks(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not (project_os(root) / 'workflow.md').exists():
        raise ProjectOSError('Missing .project_os/workflow.md. Run init first.')
    kinds = args.kind or DEFAULT_DISPATCH_KINDS
    for kind in kinds:
        if kind not in HOOK_KINDS:
            raise ProjectOSError(f'Unknown hook kind: {kind}. Expected one of: {", ".join(HOOK_KINDS)}')
    selected, malformed = select_events(root, args)
    reports: list[dict[str, Any]] = []
    for event in selected:
        for kind in kinds:
            reports.append(run_hook_kind(root, event, kind))
    payload: dict[str, Any] = {
        'generated_at': now_iso(),
        'root': root.as_posix(),
        'active_dispatcher_enabled': False,
        'manual_dispatch': True,
        'selected_events': [event_brief(event) | {'line_no': str(event.get('line_no', ''))} for event in selected],
        'malformed_event_lines': malformed,
        'reports': reports,
        'policy': 'Manual dispatcher only. No handler was auto-triggered, and no canonical state was changed.',
    }
    if args.write_report:
        output_dir = Path(args.output or '.project_os/exports/hooks').expanduser()
        if not output_dir.is_absolute():
            output_dir = root / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f'hook_report_{timestamp()}.json'
        write_json(out_path, payload)
        payload['written_report'] = relpath(root, out_path)
    print_json(payload)
    return 0
