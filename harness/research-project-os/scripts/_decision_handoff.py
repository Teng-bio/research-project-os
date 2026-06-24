from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _schema import *
from _paths import *
from _project_io import *
from _assets import refresh_asset_usage
from _task_run import (
    branch_row,
    current_branch,
    refresh_run_index,
    refresh_task_index,
    task_dir,
    task_json_path,
)
from _views import current_result_views, promotion_audit


def ensure_initialized(root: Path) -> None:
    if not (project_os(root) / 'workflow.md').exists():
        raise ProjectOSError(f'Missing {OS_DIR}/workflow.md. Run init first.')


def branch_index_row(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        'branch_id': manifest.get('branch_id', ''),
        'status': manifest.get('status', ''),
        'parent_branch_id': manifest.get('parent_branch_id') or '',
        'title': manifest.get('title', ''),
        'branch_path': manifest.get('branch_path', ''),
        'task_root': manifest.get('task_root', ''),
        'run_root': manifest.get('run_root', ''),
        'current_root': manifest.get('current_root', ''),
        'git_branch': manifest.get('git_branch') or '',
        'created_at': manifest.get('created_at', ''),
        'closed_at': manifest.get('closed_at') or '',
        'notes': manifest.get('notes', ''),
    }


def refresh_branch_index(root: Path) -> None:
    rows: list[dict[str, Any]] = []
    base = project_os(root) / 'branches'
    if base.exists():
        for branch_file in sorted(base.glob('*/branch.json')):
            rows.append(branch_index_row(read_json(branch_file)))
    write_tsv(indexes_dir(root) / 'branches.tsv', INDEX_HEADERS['branches.tsv'], rows)


def decision_journal_path(root: Path) -> Path:
    return project_os(root) / 'journals' / 'decisions.jsonl'


def append_markdown_entry(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f'# {path.stem}\n', encoding='utf-8')
    existing = path.read_text(encoding='utf-8')
    entry = f"\n\n## {title}\n\n{body.rstrip()}\n"
    path.write_text(existing.rstrip() + entry, encoding='utf-8')


def command_record_decision(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    body = args.body
    if args.body_file:
        body_path, _ = project_relative_or_absolute(root, args.body_file)
        body = body_path.read_text(encoding='utf-8')
    if not body:
        raise ProjectOSError('record-decision requires --body or --body-file')
    scope = args.scope
    branch_id = args.branch_id or current_branch(root)
    task_id = args.task_id or (current_pointer(root, 'current_task') if scope == 'task' else '')
    if scope in {'branch', 'task'} and not branch_row(root, branch_id): raise ProjectOSError(f'Missing branch: {branch_id}')
    if scope == 'task' and (not task_id or not task_json_path(root, task_id, branch_id=branch_id)): raise ProjectOSError(f'Missing task for decision scope: {task_id or "(none)"}')
    decision_id = args.decision_id or f'decision_{timestamp()}__{slugify(args.title)}'
    payload = {'decision_id': decision_id, 'scope': scope, 'branch_id': branch_id if scope in {'branch', 'task'} else '', 'task_id': task_id if scope == 'task' else '', 'title': args.title, 'body': body.rstrip(), 'status': args.status, 'created_at': now_iso(), 'notes': args.notes or ''}
    decision_journal_path(root).parent.mkdir(parents=True, exist_ok=True)
    with decision_journal_path(root).open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
    title = f"{payload['created_at']} — {args.title} (`{decision_id}`, {scope})"
    root_body = body.rstrip()
    if args.notes:
        root_body += f"\n\nNotes: {args.notes}"
    append_markdown_entry(root / 'DECISIONS.md', title, root_body)
    if scope == 'branch':
        append_markdown_entry(branch_dir(root, branch_id) / 'decisions.md', title, root_body)
    elif scope == 'task':
        tdir = task_dir(root, task_id, branch_id=branch_id)
        if tdir:
            append_markdown_entry(tdir / 'decisions.md', title, root_body)
    append_event(root, 'decision.recorded', branch_id=payload['branch_id'], task_id=payload['task_id'], detail={'decision_id': decision_id, 'scope': scope, 'title': args.title, 'status': args.status})
    print_json({'recorded_decision': decision_id, 'decision': payload}); return 0


def command_list_decisions(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    rows = read_jsonl(decision_journal_path(root))
    if args.scope: rows = [r for r in rows if r.get('scope') == args.scope]
    if args.branch_id: rows = [r for r in rows if r.get('branch_id') == args.branch_id]
    if args.task_id: rows = [r for r in rows if r.get('task_id') == args.task_id]
    if args.status: rows = [r for r in rows if r.get('status') == args.status]
    print_json({'decisions': rows, 'count': len(rows)}); return 0


def command_update_handoff(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    scope = args.scope
    branch_id = args.branch_id or current_branch(root)
    task_id = args.task_id or (current_pointer(root, 'current_task') if scope == 'task' else '')
    if scope == 'project':
        path = root / 'PROJECT_STATE.md'
    elif scope == 'branch':
        if not branch_row(root, branch_id): raise ProjectOSError(f'Missing branch: {branch_id}')
        path = branch_dir(root, branch_id) / 'handoff.md'
    else:
        if not task_id: raise ProjectOSError('update-handoff --scope task requires --task-id or current_task')
        tdir = task_dir(root, task_id, branch_id=branch_id)
        if not tdir: raise ProjectOSError(f'Missing task: {task_id}')
        path = tdir / 'handoff.md'
    message = args.message
    if args.message_file:
        message_path, _ = project_relative_or_absolute(root, args.message_file)
        message = message_path.read_text(encoding='utf-8')
    if not message:
        raise ProjectOSError('update-handoff requires --message or --message-file')
    if args.replace:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'# Handoff\n\nLast updated: {now_iso()}\n\n{message.rstrip()}\n', encoding='utf-8')
    else:
        append_markdown_entry(path, f'Handoff update {now_iso()}', message)
    append_event(root, 'handoff.updated', branch_id=branch_id if scope in {'branch', 'task'} else '', task_id=task_id if scope == 'task' else '', detail={'scope': scope, 'path': relpath(root, path), 'replace': bool(args.replace)})
    print_json({'updated_handoff': relpath(root, path), 'scope': scope, 'branch_id': branch_id if scope in {'branch', 'task'} else '', 'task_id': task_id if scope == 'task' else ''}); return 0


def command_summarize_state(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    refresh_branch_index(root); refresh_task_index(root); refresh_run_index(root); refresh_asset_usage(root)
    rows = {
        'branches': read_tsv(indexes_dir(root) / 'branches.tsv'),
        'tasks': read_tsv(indexes_dir(root) / 'tasks.tsv'),
        'runs': read_tsv(indexes_dir(root) / 'runs.tsv'),
        'results': read_tsv(indexes_dir(root) / 'results.tsv'),
        'assets': read_tsv(indexes_dir(root) / 'assets.tsv'),
        'releases': read_tsv(indexes_dir(root) / 'releases.tsv'),
    }
    focus = focus_payload(root)
    b_id = focus.get('current_branch') or current_branch(root)
    task_id = focus.get('current_task', '')
    run_id = focus.get('current_run', '')
    recent_events = read_jsonl(events_path(root))[-args.recent_events:] if events_path(root).exists() and args.recent_events else []
    current_views = current_result_views(root, rows['results'])
    audit = promotion_audit(root, rows['results'])
    branch_current = current_views['branches'].get(b_id, {'count': 0, 'results': []}) if b_id else {'count': 0, 'results': []}
    payload = {'root': root.as_posix(), 'current_branch': b_id, 'current_task': task_id, 'current_run': run_id, 'counts': {k: len(v) for k, v in rows.items()}, 'active': {
        'branch': next((r for r in rows['branches'] if r.get('branch_id') == b_id), {}),
        'task': next((r for r in rows['tasks'] if r.get('task_id') == task_id), {}),
        'run': next((r for r in rows['runs'] if r.get('run_id') == run_id), {}),
    }, 'runtime_focus': focus, 'current_results': {
        'policy': 'Derived read-only summary from .project_os/indexes/results.tsv and current/ targets; not canonical state.',
        'all_count': current_views['all']['count'],
        'project_count': current_views['project']['count'],
        'branch_count': branch_current.get('count', 0),
        'branch_id': b_id,
        'project': current_views['project']['results'],
        'branch': branch_current.get('results', []),
        'audit_ok': bool(audit.get('ok')),
        'audit_warning_counts': {
            key: len(audit.get(key, []))
            for key in ['missing_current_targets', 'cross_branch_promotions', 'unscoped_current_results', 'duplicate_current_targets']
        },
    }, 'recent_events': recent_events}
    print_json(payload); return 0
