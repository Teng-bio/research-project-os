from __future__ import annotations

import argparse
import shlex
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from _schema import DEFAULT_BRANCH
from _paths import branch_dir, indexes_dir, project_os, relpath
from _project_io import (
    ProjectOSError,
    append_event,
    current_pointer,
    current_session,
    focus_payload,
    now_iso,
    print_json,
    read_json,
    read_tsv,
    session_dir,
    sessions_dir,
    set_current_session,
    set_pointer,
    timestamp,
    validate_session_id,
    write_json,
)
from _task_run import find_run_manifest, task_json_path


SESSION_STATUSES = {'active', 'paused', 'closed'}
SESSION_CLEANUP_DEFAULT_OUTPUT = '.project_os/exports/session_cleanup'


def ensure_session_root(root: Path) -> Path:
    base = sessions_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    return base


def read_session_manifest(root: Path, session_id: str) -> dict[str, Any]:
    sid = validate_session_id(session_id)
    path = session_dir(root, sid) / 'session.json'
    if path.exists():
        return read_json(path)
    sdir = session_dir(root, sid)
    if sdir.exists():
        return {
            'session_id': sid,
            'status': 'active',
            'created_at': '',
            'updated_at': '',
            'notes': 'Legacy session directory without session.json.',
        }
    raise ProjectOSError(f'Missing session: {sid}')


def session_exists(root: Path, session_id: str) -> bool:
    return session_dir(root, session_id).exists()


def session_focus(root: Path, session_id: str) -> dict[str, str]:
    sid = validate_session_id(session_id)
    return {
        'session_id': sid,
        'current_branch': current_pointer(root, 'current_branch', session_id=sid),
        'current_task': current_pointer(root, 'current_task', session_id=sid),
        'current_run': current_pointer(root, 'current_run', session_id=sid),
    }


def validate_focus(root: Path, branch_id: str, task_id: str = '', run_id: str = '') -> None:
    branch_id = branch_id or DEFAULT_BRANCH
    if not (branch_dir(root, branch_id) / 'branch.json').exists():
        raise ProjectOSError(f'Missing branch for session focus: {branch_id}')
    if task_id:
        tjson = task_json_path(root, task_id, branch_id=branch_id)
        if not tjson:
            raise ProjectOSError(f'Missing task for session focus: {task_id} in branch {branch_id}')
    if run_id:
        manifest_path = find_run_manifest(root, run_id, branch_id=branch_id)
        if not manifest_path:
            raise ProjectOSError(f'Missing run for session focus: {run_id} in branch {branch_id}')
        manifest = read_json(manifest_path)
        run_task_id = str(manifest.get('task_id') or '')
        if task_id and run_task_id and run_task_id != task_id:
            raise ProjectOSError(f'Run {run_id} belongs to task {run_task_id}, not session task {task_id}')


def write_session_focus(root: Path, session_id: str, branch_id: str, task_id: str = '', run_id: str = '') -> None:
    sid = validate_session_id(session_id)
    validate_focus(root, branch_id, task_id, run_id)
    set_pointer(root, 'current_branch', branch_id or DEFAULT_BRANCH, session_id=sid)
    set_pointer(root, 'current_task', task_id or '', session_id=sid)
    set_pointer(root, 'current_run', run_id or '', session_id=sid)


def write_session_manifest(root: Path, session_id: str, payload: dict[str, Any]) -> None:
    sid = validate_session_id(session_id)
    path = session_dir(root, sid) / 'session.json'
    existing: dict[str, Any] = {}
    if path.exists():
        existing = read_json(path)
    merged = dict(existing)
    merged.update({
        'session_id': sid,
        'status': existing.get('status', 'active'),
        'created_at': existing.get('created_at') or now_iso(),
        'updated_at': now_iso(),
        'notes': existing.get('notes', ''),
    })
    merged.update(payload)
    if merged.get('status') not in SESSION_STATUSES:
        raise ProjectOSError(f'Invalid session status: {merged.get("status")}')
    write_json(path, merged)


def list_session_rows(root: Path) -> list[dict[str, Any]]:
    base = sessions_dir(root)
    rows: list[dict[str, Any]] = []
    if not base.exists():
        return rows
    active = current_session(root)
    for path in sorted(p for p in base.iterdir() if p.is_dir()):
        sid = path.name
        try:
            manifest = read_session_manifest(root, sid)
            focus = session_focus(root, sid)
        except ProjectOSError as exc:
            rows.append({'session_id': sid, 'error': str(exc), 'is_current': sid == active})
            continue
        rows.append({
            'session_id': sid,
            'status': manifest.get('status', ''),
            'created_at': manifest.get('created_at', ''),
            'updated_at': manifest.get('updated_at', ''),
            'closed_at': manifest.get('closed_at', ''),
            'is_current': sid == active,
            'current_branch': focus.get('current_branch', ''),
            'current_task': focus.get('current_task', ''),
            'current_run': focus.get('current_run', ''),
            'notes': manifest.get('notes', ''),
        })
    return rows


def command_create_session(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not (project_os(root) / 'workflow.md').exists():
        raise ProjectOSError('Missing .project_os/workflow.md. Run init first.')
    sid = validate_session_id(args.session_id)
    sdir = session_dir(root, sid)
    if sdir.exists() and not args.replace:
        raise ProjectOSError(f'Session already exists: {sid}')
    ensure_session_root(root)
    sdir.mkdir(parents=True, exist_ok=True)
    branch_id = args.branch_id or current_pointer(root, 'current_branch') or DEFAULT_BRANCH
    task_id = '' if args.no_task else (args.task_id if args.task_id is not None and args.task_id != '' else current_pointer(root, 'current_task'))
    run_id = '' if args.no_run else (args.run_id if args.run_id is not None and args.run_id != '' else current_pointer(root, 'current_run'))
    if args.no_task:
        run_id = ''
    write_session_focus(root, sid, branch_id, task_id, run_id)
    write_session_manifest(root, sid, {'status': 'active', 'title': args.title or sid, 'notes': args.notes})
    if args.set_current:
        set_current_session(root, sid)
    append_event(root, 'session.created', branch_id=branch_id, task_id=task_id, run_id=run_id, detail={'session_id': sid, 'set_current': bool(args.set_current), 'title': args.title or sid})
    print_json({'created_session': sid, 'path': relpath(root, sdir), 'set_current': bool(args.set_current), 'focus': session_focus(root, sid), 'active_focus': focus_payload(root)})
    return 0


def command_set_current_session(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if args.clear:
        previous = current_session(root)
        set_current_session(root, '')
        append_event(root, 'session.changed', detail={'previous_session': previous, 'current_session': ''})
        print_json({'current_session': '', 'previous_session': previous, 'active_focus': focus_payload(root)})
        return 0
    if not args.session_id:
        raise ProjectOSError('set-current-session requires --session-id or --clear')
    sid = validate_session_id(args.session_id)
    manifest = read_session_manifest(root, sid)
    if manifest.get('status') == 'closed':
        raise ProjectOSError(f'Cannot activate closed session: {sid}')
    if manifest.get('status') == 'paused':
        raise ProjectOSError(f'Cannot activate paused session: {sid}. Use resume-session first.')
    focus = session_focus(root, sid)
    validate_focus(root, focus.get('current_branch', '') or DEFAULT_BRANCH, focus.get('current_task', ''), focus.get('current_run', ''))
    set_current_session(root, sid)
    write_session_manifest(root, sid, {'status': manifest.get('status', 'active'), 'notes': manifest.get('notes', '')})
    append_event(root, 'session.changed', branch_id=focus.get('current_branch', ''), task_id=focus.get('current_task', ''), run_id=focus.get('current_run', ''), detail={'current_session': sid})
    print_json({'current_session': sid, 'active_focus': focus_payload(root)})
    return 0


def command_list_sessions(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    rows = list_session_rows(root)
    if args.status:
        rows = [row for row in rows if row.get('status') == args.status]
    print_json({'current_session': current_session(root), 'sessions': rows, 'count': len(rows)})
    return 0


def command_show_session(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    sid = args.session_id or current_session(root)
    if not sid:
        print_json({'current_session': '', 'active_focus': focus_payload(root), 'session': {}})
        return 0
    manifest = read_session_manifest(root, sid)
    focus = session_focus(root, sid)
    print_json({'current_session': current_session(root), 'session': manifest, 'focus': focus, 'is_current': sid == current_session(root), 'path': relpath(root, session_dir(root, sid))})
    return 0


def command_set_session_focus(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    sid = validate_session_id(args.session_id)
    manifest = read_session_manifest(root, sid)
    if manifest.get('status') == 'closed':
        raise ProjectOSError(f'Cannot update closed session: {sid}')
    if manifest.get('status') == 'paused':
        raise ProjectOSError(f'Cannot update paused session: {sid}. Use resume-session first.')
    old = session_focus(root, sid)
    branch_id = args.branch_id or old.get('current_branch') or DEFAULT_BRANCH
    if args.clear_task:
        task_id = ''
    else:
        task_id = args.task_id if args.task_id else old.get('current_task', '')
    if args.clear_run or not task_id:
        run_id = ''
    else:
        run_id = args.run_id if args.run_id else old.get('current_run', '')
    write_session_focus(root, sid, branch_id, task_id, run_id)
    write_session_manifest(root, sid, {'status': manifest.get('status', 'active'), 'notes': args.notes if args.notes else manifest.get('notes', '')})
    if args.set_current:
        set_current_session(root, sid)
    new_focus = session_focus(root, sid)
    append_event(root, 'session.changed', branch_id=new_focus.get('current_branch', ''), task_id=new_focus.get('current_task', ''), run_id=new_focus.get('current_run', ''), detail={'session_id': sid, 'focus_updated': True, 'set_current': bool(args.set_current)})
    print_json({'session_id': sid, 'focus': new_focus, 'set_current': bool(args.set_current), 'active_focus': focus_payload(root)})
    return 0


def command_pause_session(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    sid = validate_session_id(args.session_id)
    manifest = read_session_manifest(root, sid)
    if manifest.get('status') == 'closed':
        raise ProjectOSError(f'Cannot pause closed session: {sid}')
    focus = session_focus(root, sid)
    already_paused = manifest.get('status') == 'paused'
    cleared = False
    if current_session(root) == sid:
        set_current_session(root, '')
        cleared = True
    write_session_manifest(root, sid, {
        'status': 'paused',
        'paused_at': manifest.get('paused_at') or now_iso(),
        'notes': args.notes if args.notes else manifest.get('notes', ''),
    })
    append_event(root, 'session.paused', branch_id=focus.get('current_branch', ''), task_id=focus.get('current_task', ''), run_id=focus.get('current_run', ''), detail={'session_id': sid, 'cleared_current_session': cleared, 'already_paused': already_paused, 'notes': args.notes})
    print_json({'paused_session': sid, 'already_paused': already_paused, 'cleared_current_session': cleared, 'session': read_session_manifest(root, sid), 'active_focus': focus_payload(root)})
    return 0


def command_resume_session(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    sid = validate_session_id(args.session_id)
    manifest = read_session_manifest(root, sid)
    if manifest.get('status') == 'closed':
        raise ProjectOSError(f'Cannot resume closed session: {sid}')
    focus = session_focus(root, sid)
    validate_focus(root, focus.get('current_branch', '') or DEFAULT_BRANCH, focus.get('current_task', ''), focus.get('current_run', ''))
    already_active = manifest.get('status') == 'active'
    write_session_manifest(root, sid, {
        'status': 'active',
        'resumed_at': now_iso(),
        'notes': args.notes if args.notes else manifest.get('notes', ''),
    })
    if args.set_current:
        set_current_session(root, sid)
    append_event(root, 'session.resumed', branch_id=focus.get('current_branch', ''), task_id=focus.get('current_task', ''), run_id=focus.get('current_run', ''), detail={'session_id': sid, 'set_current': bool(args.set_current), 'already_active': already_active, 'notes': args.notes})
    print_json({'resumed_session': sid, 'already_active': already_active, 'set_current': bool(args.set_current), 'session': read_session_manifest(root, sid), 'active_focus': focus_payload(root)})
    return 0


def command_close_session(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    sid = validate_session_id(args.session_id)
    manifest = read_session_manifest(root, sid)
    focus = session_focus(root, sid)
    write_session_manifest(root, sid, {'status': 'closed', 'closed_at': now_iso(), 'notes': args.notes if args.notes else manifest.get('notes', '')})
    cleared = False
    if current_session(root) == sid:
        set_current_session(root, '')
        cleared = True
    append_event(root, 'session.closed', branch_id=focus.get('current_branch', ''), task_id=focus.get('current_task', ''), run_id=focus.get('current_run', ''), detail={'session_id': sid, 'cleared_current_session': cleared, 'notes': args.notes})
    print_json({'closed_session': sid, 'cleared_current_session': cleared, 'active_focus': focus_payload(root)})
    return 0


def parse_session_time(value: str) -> datetime | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def session_age_anchor(manifest: dict[str, Any]) -> tuple[str, str]:
    status = str(manifest.get('status') or '')
    if status == 'closed' and manifest.get('closed_at'):
        return 'closed_at', str(manifest.get('closed_at') or '')
    if status == 'paused' and manifest.get('paused_at'):
        return 'paused_at', str(manifest.get('paused_at') or '')
    if manifest.get('updated_at'):
        return 'updated_at', str(manifest.get('updated_at') or '')
    if manifest.get('created_at'):
        return 'created_at', str(manifest.get('created_at') or '')
    return '', ''


def session_age_days(manifest: dict[str, Any], now: datetime | None = None) -> float | None:
    _, anchor = session_age_anchor(manifest)
    parsed = parse_session_time(anchor)
    if not parsed:
        return None
    current = now or datetime.now().astimezone()
    return max(0.0, (current - parsed.astimezone(current.tzinfo)).total_seconds() / 86400.0)


def session_cleanup_suggestions(root: Path, row: dict[str, Any]) -> list[str]:
    sid = str(row.get('session_id') or '')
    status = str(row.get('status') or '')
    def command(subcommand: str, extra: list[str] | None = None) -> str:
        argv = [sys.executable, (Path(__file__).resolve().parent / 'project_os.py').as_posix(), subcommand, '--root', root.as_posix()]
        if extra:
            argv.extend(extra)
        return ' '.join(shlex.quote(part) for part in argv)

    suggestions = [command('show-session', ['--session-id', sid])]
    if status == 'paused':
        suggestions.append(command('resume-session', ['--session-id', sid]))
        suggestions.append(command('close-session', ['--session-id', sid]))
    elif status == 'closed':
        suggestions.append(command('export-dashboard', ['--apply']))
    elif status == 'active':
        suggestions.append(command('pause-session', ['--session-id', sid]))
    return suggestions


def build_session_cleanup_plan(root: Path, *, statuses: list[str] | None = None, min_age_days: int = 0, include_current: bool = False) -> dict[str, Any]:
    selected_statuses = statuses or ['closed']
    invalid = [status for status in selected_statuses if status not in SESSION_STATUSES]
    if invalid:
        raise ProjectOSError(f'Invalid session cleanup status: {", ".join(invalid)}')
    if min_age_days < 0:
        raise ProjectOSError('--min-age-days must be >= 0')

    active_sid = current_session(root)
    now = datetime.now().astimezone()
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for row in list_session_rows(root):
        sid = str(row.get('session_id') or '')
        if row.get('error'):
            warnings.append({'session_id': sid, 'issue': row.get('error')})
            continue
        try:
            manifest = read_session_manifest(root, sid)
        except ProjectOSError as exc:
            warnings.append({'session_id': sid, 'issue': str(exc)})
            continue
        status = str(manifest.get('status') or row.get('status') or '')
        if status not in selected_statuses:
            skipped.append({'session_id': sid, 'status': status, 'reason': 'status_not_selected'})
            continue
        if sid == active_sid and not include_current:
            skipped.append({'session_id': sid, 'status': status, 'reason': 'current_session_excluded'})
            continue

        anchor_field, anchor_value = session_age_anchor(manifest)
        age = session_age_days(manifest, now=now)
        if age is not None and age < min_age_days:
            skipped.append({
                'session_id': sid,
                'status': status,
                'reason': 'younger_than_min_age_days',
                'age_days': round(age, 3),
                'min_age_days': min_age_days,
                'age_anchor': anchor_field,
            })
            continue

        sdir = session_dir(root, sid)
        focus = session_focus(root, sid)
        candidates.append({
            'session_id': sid,
            'status': status,
            'is_current': sid == active_sid,
            'age_days': None if age is None else round(age, 3),
            'age_anchor': anchor_field,
            'age_anchor_value': anchor_value,
            'session_dir': relpath(root, sdir),
            'manifest_path': relpath(root, sdir / 'session.json'),
            'pointer_paths': {
                'current_branch': relpath(root, sdir / 'current_branch'),
                'current_task': relpath(root, sdir / 'current_task'),
                'current_run': relpath(root, sdir / 'current_run'),
            },
            'focus': focus,
            'notes': manifest.get('notes', ''),
            'suggested_review_commands': session_cleanup_suggestions(root, row),
            'cleanup_policy': 'Review-only candidate; the harness does not delete or move session directories automatically.',
        })

    return {
        'generated_at': now.isoformat(timespec='seconds'),
        'policy': {
            'mode': 'dry_run_report_only',
            'default_statuses': ['closed'],
            'selected_statuses': selected_statuses,
            'min_age_days': min_age_days,
            'include_current': include_current,
            'canonical_state_unchanged': True,
            'automatic_delete_or_move': False,
            'notes': [
                'Session cleanup reports are generated inspection views.',
                'They do not delete, move, archive, or rewrite runtime session directories.',
                'If physical cleanup is ever added, it must remain explicit, reviewed, and validation-gated.',
            ],
        },
        'current_session': active_sid,
        'candidate_count': len(candidates),
        'skipped_count': len(skipped),
        'warning_count': len(warnings),
        'candidates': candidates,
        'skipped': skipped,
        'warnings': warnings,
    }


def command_plan_session_cleanup(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    statuses = args.status or ['closed']
    plan = build_session_cleanup_plan(
        root,
        statuses=statuses,
        min_age_days=int(args.min_age_days or 0),
        include_current=bool(args.include_current),
    )
    if args.write_report:
        output = root / (args.output or SESSION_CLEANUP_DEFAULT_OUTPUT)
        if Path(args.output or '').is_absolute():
            output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / f'session_cleanup_plan_{timestamp()}.json'
        write_json(report_path, plan)
        plan['written_report'] = relpath(root, report_path)
    print_json(plan)
    return 0


def validate_sessions(root: Path, errors: list[dict[str, str]], warnings: list[dict[str, str]]) -> None:
    runtime = project_os(root) / 'runtime'
    current_session_path = runtime / 'current_session'
    active_sid = current_session(root) if current_session_path.exists() else ''
    if active_sid:
        try:
            validate_session_id(active_sid)
        except ProjectOSError as exc:
            errors.append({'path': current_session_path.as_posix(), 'issue': str(exc)})
            return
        if not session_dir(root, active_sid).exists():
            errors.append({'path': current_session_path.as_posix(), 'issue': f'points to missing session: {active_sid}'})
        else:
            try:
                active_manifest = read_session_manifest(root, active_sid)
                if active_manifest.get('status') != 'active':
                    errors.append({'path': current_session_path.as_posix(), 'issue': f'points to non-active session {active_sid} with status {active_manifest.get("status")}'})
            except ProjectOSError as exc:
                errors.append({'path': current_session_path.as_posix(), 'issue': str(exc)})

    base = sessions_dir(root)
    if not base.exists():
        return
    for sdir in sorted(p for p in base.iterdir() if p.is_dir()):
        sid = sdir.name
        try:
            validate_session_id(sid)
        except ProjectOSError as exc:
            errors.append({'path': sdir.as_posix(), 'issue': str(exc)})
            continue
        manifest_path = sdir / 'session.json'
        if not manifest_path.exists():
            warnings.append({'path': manifest_path.as_posix(), 'issue': 'missing session manifest'})
        else:
            try:
                manifest = read_json(manifest_path)
            except ProjectOSError as exc:
                errors.append({'path': manifest_path.as_posix(), 'issue': str(exc)})
                continue
            if manifest.get('session_id') and manifest.get('session_id') != sid:
                errors.append({'path': manifest_path.as_posix(), 'issue': f'session_id mismatch: {manifest.get("session_id")} != {sid}'})
            if manifest.get('status') and manifest.get('status') not in SESSION_STATUSES:
                warnings.append({'path': manifest_path.as_posix(), 'issue': f'nonstandard session status: {manifest.get("status")}'})
        for name in ['current_branch', 'current_task', 'current_run']:
            if not (sdir / name).exists():
                errors.append({'path': (sdir / name).as_posix(), 'issue': 'missing session runtime pointer'})
        branch_id = current_pointer(root, 'current_branch', session_id=sid)
        task_id = current_pointer(root, 'current_task', session_id=sid)
        run_id = current_pointer(root, 'current_run', session_id=sid)
        if branch_id and not (branch_dir(root, branch_id) / 'branch.json').exists():
            errors.append({'path': (sdir / 'current_branch').as_posix(), 'issue': f'points to missing branch: {branch_id}'})
        if task_id and not task_json_path(root, task_id, branch_id=branch_id or None):
            errors.append({'path': (sdir / 'current_task').as_posix(), 'issue': f'points to missing task in session branch: {task_id}'})
        if run_id and not find_run_manifest(root, run_id, branch_id=branch_id or None):
            errors.append({'path': (sdir / 'current_run').as_posix(), 'issue': f'points to missing run in session branch: {run_id}'})


def session_summary_for_dashboard(root: Path) -> dict[str, Any]:
    return {
        'current_session': current_session(root),
        'active_focus': focus_payload(root),
        'sessions': list_session_rows(root),
    }
