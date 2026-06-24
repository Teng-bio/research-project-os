from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from _schema import *
from _paths import *
from _project_io import *
from _views import current_result_views, promotion_audit, refresh_data_assets_markdown, refresh_results_index_markdown
from _assets import refresh_asset_usage, sync_primary_locations_from_assets
from _task_run import create_task_record, find_run_manifest, refresh_run_index, refresh_task_index, task_json_path
from _sessions import session_summary_for_dashboard


def ensure_initialized(root: Path) -> None:
    if not (project_os(root) / 'workflow.md').exists():
        raise ProjectOSError(f'Missing {OS_DIR}/workflow.md. Run init first.')


def write_missing_file(path: Path, text: str, apply: bool, actions: list[dict[str, str]]) -> None:
    if path.exists():
        actions.append({'status': 'exists', 'path': path.as_posix()})
        return
    actions.append({'status': 'create' if apply else 'would_create', 'path': path.as_posix()})
    if apply:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


def ensure_dir(path: Path, apply: bool, actions: list[dict[str, str]]) -> None:
    if path.exists():
        actions.append({'status': 'exists', 'path': path.as_posix()})
        return
    actions.append({'status': 'mkdir' if apply else 'would_mkdir', 'path': path.as_posix()})
    if apply:
        path.mkdir(parents=True, exist_ok=True)


def project_id_from_root(root: Path) -> str:
    return slugify(root.name, max_len=64)


def project_json_payload(root: Path, profile: str = 'research') -> dict[str, Any]:
    return {
        'project_id': project_id_from_root(root),
        'schema_version': SCHEMA_VERSION,
        'profile': profile,
        'harness_version': HARNESS_VERSION,
        'created_at': now_iso(),
        'default_branch': DEFAULT_BRANCH,
    }


def branch_row(root: Path, branch_id: str) -> dict[str, str] | None:
    for row in read_tsv(indexes_dir(root) / 'branches.tsv'):
        if row.get('branch_id') == branch_id:
            return row
    bj = branch_dir(root, branch_id) / 'branch.json'
    if bj.exists():
        data = read_json(bj)
        return {h: '' if data.get(h) is None else str(data.get(h, '')) for h in INDEX_HEADERS['branches.tsv']}
    return None


def current_branch(root: Path) -> str:
    return current_pointer(root, 'current_branch') or DEFAULT_BRANCH


def branch_manifest(root: Path, branch_id: str) -> dict[str, Any]:
    path = branch_dir(root, branch_id) / 'branch.json'
    if not path.exists():
        raise ProjectOSError(f'Missing branch: {branch_id}')
    return read_json(path)


def branch_index_row(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
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
            rows.append(branch_index_row(root, read_json(branch_file)))
    write_tsv(indexes_dir(root) / 'branches.tsv', INDEX_HEADERS['branches.tsv'], rows)


def create_branch_record(
    root: Path,
    branch_id: str,
    title: str,
    *,
    parent_branch_id: str = '',
    git_branch: str = '',
    notes: str = '',
    status: str = 'active',
    set_current: bool = False,
    allow_existing: bool = False,
) -> dict[str, Any]:
    if status not in BRANCH_STATUSES:
        raise ProjectOSError(f'Invalid branch status: {status}')
    bdir = branch_dir(root, branch_id)
    existed_before = (bdir / 'branch.json').exists()
    if existed_before and not allow_existing:
        raise ProjectOSError(f'Branch already exists: {branch_id}')
    created = now_iso()
    for directory in [bdir, bdir / 'research', bdir / 'notes', bdir / 'tasks', branch_current_dir(root, branch_id), root / 'runs' / branch_id]:
        directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        'branch_id': branch_id,
        'title': title,
        'status': status,
        'parent_branch_id': parent_branch_id or '',
        'git_branch': git_branch or None,
        'branch_path': relpath(root, bdir),
        'task_root': relpath(root, bdir / 'tasks'),
        'run_root': f'runs/{branch_id}',
        'current_root': relpath(root, branch_current_dir(root, branch_id)),
        'created_at': created,
        'closed_at': None,
        'objective_file': 'objective.md',
        'context_file': 'context.md',
        'handoff_file': 'handoff.md',
        'notes': notes or '',
    }
    if allow_existing and (bdir / 'branch.json').exists():
        old = read_json(bdir / 'branch.json')
        manifest['created_at'] = old.get('created_at') or created
        manifest['closed_at'] = old.get('closed_at')
        if old.get('status') and branch_id == DEFAULT_BRANCH:
            manifest['status'] = old.get('status')
    write_json(bdir / 'branch.json', manifest)
    write_missing_text_if_absent(bdir / 'objective.md', f'# Objective\n\n{title}\n')
    write_missing_text_if_absent(bdir / 'context.md', '# Context\n\nBranch-level context.\n')
    write_missing_text_if_absent(bdir / 'handoff.md', '# Handoff\n\nBranch handoff notes.\n')
    write_missing_text_if_absent(bdir / 'decisions.md', '# Decisions\n\n')
    upsert_tsv(indexes_dir(root) / 'branches.tsv', INDEX_HEADERS['branches.tsv'], 'branch_id', branch_index_row(root, manifest))
    if set_current:
        set_pointer(root, 'current_branch', branch_id)
    append_event(root, 'branch.changed' if existed_before else 'branch.created', branch_id=branch_id, detail={'title': title, 'status': manifest['status']})
    return {'branch_id': branch_id, 'path': relpath(root, bdir), 'set_current': bool(set_current)}


def init_harness(root: Path, apply: bool, *, title: str = 'Untitled project', profile: str = 'research') -> list[dict[str, str]]:
    os_dir = project_os(root)
    actions: list[dict[str, str]] = []
    dirs = [
        os_dir, os_dir / 'spec', os_dir / 'runtime', os_dir / 'runtime' / 'sessions', os_dir / 'journals', os_dir / 'indexes', os_dir / 'exports', os_dir / 'branches',
        branch_dir(root, DEFAULT_BRANCH), branch_dir(root, DEFAULT_BRANCH) / 'tasks', branch_dir(root, DEFAULT_BRANCH) / 'research', branch_dir(root, DEFAULT_BRANCH) / 'notes',
        root / 'runs' / DEFAULT_BRANCH, branch_current_dir(root, DEFAULT_BRANCH), root / 'current' / 'project', root / 'release',
    ]
    for directory in dirs:
        ensure_dir(directory, apply, actions)
    write_missing_file(os_dir / 'project.json', json.dumps(project_json_payload(root, profile), ensure_ascii=False, indent=2) + '\n', apply, actions)
    write_missing_file(events_path(root), '', apply, actions)
    write_missing_file(os_dir / 'workflow.md', WORKFLOW_TEXT, apply, actions)
    write_missing_file(os_dir / 'config.yaml', CONFIG_TEXT, apply, actions)
    for name, text in SPEC_TEXTS.items():
        write_missing_file(os_dir / 'spec' / name, text, apply, actions)
    for pointer, value in [('current_branch', DEFAULT_BRANCH), ('current_task', ''), ('current_run', '')]:
        path = os_dir / 'runtime' / pointer
        if path.exists():
            actions.append({'status': 'exists', 'path': path.as_posix()})
        else:
            actions.append({'status': 'create' if apply else 'would_create', 'path': path.as_posix()})
            if apply:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value + ('\n' if value else ''), encoding='utf-8')
    current_session_path = os_dir / 'runtime' / 'current_session'
    if current_session_path.exists():
        actions.append({'status': 'exists', 'path': current_session_path.as_posix()})
    else:
        actions.append({'status': 'create' if apply else 'would_create', 'path': current_session_path.as_posix()})
        if apply:
            current_session_path.parent.mkdir(parents=True, exist_ok=True)
            current_session_path.write_text('', encoding='utf-8')
    for name, headers in INDEX_HEADERS.items():
        write_missing_file(os_dir / 'indexes' / name, '\t'.join(headers) + '\n', apply, actions)
    for name, text in ROOT_DOC_DEFAULTS.items():
        write_missing_file(root / name, text, apply, actions)
    if apply:
        create_branch_record(root, DEFAULT_BRANCH, 'Main analysis line', notes=f'Default branch for {title}', set_current=True, allow_existing=True)
        append_event(root, 'project.initialized', branch_id=DEFAULT_BRANCH, detail={'title': title, 'profile': profile, 'schema_version': SCHEMA_VERSION})
    else:
        actions.append({'status': 'would_create_or_update', 'path': f'{OS_DIR}/branches/{DEFAULT_BRANCH}/branch.json'})
        actions.append({'status': 'would_append', 'path': f'{OS_DIR}/journals/events.jsonl'})
    return actions


def command_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    actions = init_harness(root, args.apply, title=args.title, profile=args.profile)
    print_json({'root': root.as_posix(), 'applied': bool(args.apply), 'actions': actions})
    return 0


def command_restore_journal(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    path = events_path(root)
    actions: list[dict[str, str]] = []
    restored = False

    if args.apply and not getattr(args, 'approved', False):
        raise ProjectOSError('restore-journal --apply requires --approved')

    if path.exists():
        actions.append({'status': 'exists', 'path': relpath(root, path)})
    else:
        actions.append({'status': 'exists' if path.parent.exists() else ('mkdir' if args.apply else 'would_mkdir'), 'path': relpath(root, path.parent)})
        actions.append({'status': 'create' if args.apply else 'would_create', 'path': relpath(root, path)})
        actions.append({'status': 'append' if args.apply else 'would_append', 'path': relpath(root, path), 'event': 'journal.restored'})
        if args.apply:
            append_event(
                root,
                'journal.restored',
                branch_id=current_branch(root),
                detail={
                    'command': 'restore-journal',
                    'reason': args.reason or 'missing events.jsonl',
                    'policy': 'created missing event journal; did not reconstruct historical lifecycle events',
                },
            )
            restored = True

    print_json({
        'root': root.as_posix(),
        'applied': bool(args.apply),
        'approved': bool(getattr(args, 'approved', False)),
        'restored': restored,
        'journal': relpath(root, path),
        'actions': actions,
        'policy': 'restore-journal only creates a missing events.jsonl and appends journal.restored; it does not overwrite existing journals or synthesize historical events.',
        'next': 'Run validate/doctor. If existing objects lack event coverage, review provenance with summarize-state instead of hand-editing events.',
    })
    return 0


def managed_block_content(existing: str, block: str) -> str:
    start = existing.find(PROJECT_OS_BLOCK_START)
    if start == -1:
        trimmed = existing.rstrip()
        return (trimmed + '\n\n' if trimmed else '') + block.rstrip() + '\n'
    end = existing.find(PROJECT_OS_BLOCK_END, start)
    if end == -1:
        trimmed = existing.rstrip()
        return trimmed + '\n\n' + block.rstrip() + '\n'
    end += len(PROJECT_OS_BLOCK_END)
    return existing[:start] + block.rstrip() + existing[end:].lstrip('\n')


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.replace('\r\n', '\n').encode('utf-8')).hexdigest()


def update_template_hashes(root: Path, files: dict[str, str]) -> None:
    path = project_os(root) / '.template-hashes.json'
    payload: dict[str, Any] = {'__version': 1, 'hashes': {}}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                payload.update(loaded)
                if not isinstance(payload.get('hashes'), dict):
                    payload['hashes'] = {}
        except json.JSONDecodeError:
            payload = {'__version': 1, 'hashes': {}}
    hashes = payload.setdefault('hashes', {})
    for rel, content in files.items():
        hashes[rel] = compute_hash(content)
    write_json(path, payload)


def install_codex_adapter(root: Path, apply: bool) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    written_templates: dict[str, str] = {}
    agents_path = root / 'AGENTS.md'
    existing = agents_path.read_text(encoding='utf-8') if agents_path.exists() else ''
    new = managed_block_content(existing, PROJECT_OS_AGENTS_BLOCK)
    if existing == new:
        actions.append({'status': 'exists', 'path': 'AGENTS.md'})
    else:
        actions.append({'status': ('update' if agents_path.exists() else 'create') if apply else ('would_update' if agents_path.exists() else 'would_create'), 'path': 'AGENTS.md'})
        if apply:
            agents_path.write_text(new, encoding='utf-8')
            written_templates['AGENTS.md#PROJECT_OS_BLOCK'] = PROJECT_OS_AGENTS_BLOCK
    repo_skill_path = root / '.agents' / 'skills' / 'project-skeleton' / 'SKILL.md'
    rel_skill = relpath(root, repo_skill_path)
    if repo_skill_path.exists() and repo_skill_path.read_text(encoding='utf-8') == REPO_PROJECT_SKELETON_SKILL:
        actions.append({'status': 'exists', 'path': rel_skill})
    else:
        actions.append({'status': ('update' if repo_skill_path.exists() else 'create') if apply else ('would_update' if repo_skill_path.exists() else 'would_create'), 'path': rel_skill})
        if apply:
            repo_skill_path.parent.mkdir(parents=True, exist_ok=True)
            repo_skill_path.write_text(REPO_PROJECT_SKELETON_SKILL, encoding='utf-8')
            written_templates[rel_skill] = REPO_PROJECT_SKELETON_SKILL
    if apply and written_templates:
        update_template_hashes(root, written_templates)
    return actions


def install_claude_adapter(root: Path, apply: bool) -> list[dict[str, str]]:
    path = root / 'CLAUDE.md'
    existing = path.read_text(encoding='utf-8') if path.exists() else ''
    new = managed_block_content(existing, CLAUDE_BLOCK)
    if existing == new:
        return [{'status': 'exists', 'path': 'CLAUDE.md'}]
    status = ('update' if path.exists() else 'create') if apply else ('would_update' if path.exists() else 'would_create')
    if apply:
        path.write_text(new, encoding='utf-8')
        update_template_hashes(root, {'CLAUDE.md#PROJECT_OS_BLOCK': CLAUDE_BLOCK})
    return [{'status': status, 'path': 'CLAUDE.md'}]


def parse_platforms(raw_platforms: list[str]) -> set[str]:
    return {item.strip().lower().replace('-', '_') for raw in raw_platforms for item in raw.split(',') if item.strip()}


def command_install_adapters(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    platforms = parse_platforms(args.platforms) or {'codex'}
    actions: list[dict[str, str]] = []
    if 'codex' in platforms:
        actions.extend(install_codex_adapter(root, args.apply))
    if 'claude' in platforms or 'claude_code' in platforms:
        actions.extend(install_claude_adapter(root, args.apply))
    unsupported = sorted(platforms - {'codex', 'claude', 'claude_code'})
    for platform in unsupported:
        actions.append({'status': 'unsupported', 'path': platform})
    if args.apply:
        append_event(root, 'state.updated', branch_id=current_branch(root), detail={'command': 'install-adapters', 'platforms': sorted(platforms)})
    print_json({'root': root.as_posix(), 'applied': bool(args.apply), 'platforms': sorted(platforms), 'actions': actions})
    return 0


def command_new_project(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    actions = init_harness(root, args.apply, title=args.title, profile=args.profile)
    adapter_actions: list[dict[str, str]] = []
    platforms = parse_platforms(args.platforms) or {'codex'}
    if args.install_adapters and args.apply:
        if 'codex' in platforms:
            adapter_actions.extend(install_codex_adapter(root, True))
        if 'claude' in platforms or 'claude_code' in platforms:
            adapter_actions.extend(install_claude_adapter(root, True))
        for platform in sorted(platforms - {'codex', 'claude', 'claude_code'}):
            adapter_actions.append({'status': 'unsupported', 'path': platform})
    elif args.install_adapters:
        for platform in sorted(platforms):
            adapter_actions.append({'status': 'would_install', 'path': platform})
    bootstrap_task = ''
    if args.apply and args.bootstrap_task:
        task_title = args.bootstrap_title or f'Bootstrap project skeleton: {args.title}'
        task_id = f"{datetime.now().strftime('%Y%m%d')}_{slugify(task_title)}"
        if not task_json_path(root, task_id):
            create_task_record(root, title=task_title, kind='planning', task_id=task_id, branch_id=DEFAULT_BRANCH, stage='Intake', notes=f'Created by project_os.py new-project; profile={args.profile}', set_current=True)
        bootstrap_task = task_id
    print_json({'root': root.as_posix(), 'title': args.title, 'profile': args.profile, 'platforms': sorted(platforms), 'applied': bool(args.apply), 'actions': actions, 'adapter_actions': adapter_actions, 'bootstrap_task': bootstrap_task, 'next': 'Run project_os.py start --root <project> or trigger 项目骨架/开工.'})
    return 0


def count_rows(path: Path) -> int:
    return len(read_tsv(path)) if path.exists() else 0


def recency_value(row: dict[str, str]) -> str:
    return row.get('closed_at') or row.get('created_at') or ''


def most_recent_row(rows: list[dict[str, str]]) -> dict[str, str]:
    if not rows:
        return {}
    return max(rows, key=lambda row: (recency_value(row), row.get('run_id') or row.get('result_id') or ''))


def recent_rows(rows: list[dict[str, str]], limit: int = 5) -> list[dict[str, str]]:
    return sorted(rows, key=lambda row: (recency_value(row), row.get('run_id') or row.get('result_id') or ''), reverse=True)[:limit]


def status_runs_summary(runs: list[dict[str, str]], focus: dict[str, str]) -> dict[str, Any]:
    branch_id = focus.get('current_branch', '')
    task_id = focus.get('current_task', '')
    run_id = focus.get('current_run', '')
    active_runs = [row for row in runs if row.get('status') == 'active']
    open_runs = [row for row in runs if row.get('status') in {'active', 'pending_review'}]
    current_run_row = next((row for row in runs if row.get('run_id') == run_id), {})
    return {
        'policy': 'Read-only summary from .project_os/indexes/runs.tsv; status does not refresh indexes or modify run manifests.',
        'active_count': len(active_runs),
        'open_count': len(open_runs),
        'active_runs': active_runs,
        'current_branch_active_count': len([row for row in active_runs if row.get('branch_id') == branch_id]) if branch_id else 0,
        'current_task_active_count': len([row for row in active_runs if row.get('task_id') == task_id]) if task_id else 0,
        'current_run': current_run_row,
        'last_run': most_recent_row(runs),
        'last_run_basis': 'closed_at when present, otherwise created_at, from runs.tsv',
    }


def status_results_summary(root: Path, results: list[dict[str, str]], focus: dict[str, str]) -> dict[str, Any]:
    branch_id = focus.get('current_branch', '')
    candidate_rows = [row for row in results if row.get('status') == 'candidate']
    accepted_rows = [row for row in results if row.get('status') == 'accepted']
    status_current_rows = [row for row in results if row.get('status') == 'current']
    current_views = current_result_views(root, results)
    audit = promotion_audit(root, results)
    branch_view = current_views['branches'].get(branch_id, {'count': 0, 'results': []}) if branch_id else {'count': 0, 'results': []}
    return {
        'policy': 'Derived read-only summary from .project_os/indexes/results.tsv and current/ targets; status does not promote, repair current/, or rewrite results.tsv.',
        'candidate_count': len(candidate_rows),
        'accepted_count': len(accepted_rows),
        'current_status_count': len(status_current_rows),
        'current_count': current_views['all']['count'],
        'project_current_count': current_views['project']['count'],
        'branch_current_count': branch_view.get('count', 0),
        'branch_id': branch_id,
        'latest_candidate_results': recent_rows(candidate_rows, limit=5),
        'project_current_results': current_views['project']['results'],
        'branch_current_results': branch_view.get('results', []),
        'audit_ok': bool(audit.get('ok')),
        'audit_warning_counts': {
            key: len(audit.get(key, []))
            for key in ['missing_current_targets', 'cross_branch_promotions', 'unscoped_current_results', 'duplicate_current_targets']
        },
    }


def command_status(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    os_dir = project_os(root)
    initialized = (os_dir / 'workflow.md').exists()
    indexes = indexes_dir(root)
    focus = focus_payload(root) if initialized else {}
    runs = read_tsv(indexes / 'runs.tsv') if initialized else []
    results = read_tsv(indexes / 'results.tsv') if initialized else []
    payload = {
        'root': root.as_posix(),
        'initialized': initialized,
        'project': read_json(os_dir / 'project.json') if (os_dir / 'project.json').exists() else {},
        'current_session': focus.get('session_id', '') if initialized else '',
        'runtime_focus_source': focus.get('source', '') if initialized else '',
        'runtime_focus': focus,
        'current_branch': focus.get('current_branch', '') if initialized else '',
        'current_task': focus.get('current_task', '') if initialized else '',
        'current_run': focus.get('current_run', '') if initialized else '',
        'counts': {
            'branches': count_rows(indexes / 'branches.tsv'),
            'tasks': count_rows(indexes / 'tasks.tsv'),
            'runs': count_rows(indexes / 'runs.tsv'),
            'results': count_rows(indexes / 'results.tsv'),
            'assets': count_rows(indexes / 'assets.tsv'),
            'releases': count_rows(indexes / 'releases.tsv'),
            'sessions': len(session_summary_for_dashboard(root).get('sessions', [])),
        } if initialized else {},
        'runs_summary': status_runs_summary(runs, focus) if initialized else {},
        'results_summary': status_results_summary(root, results, focus) if initialized else {},
    }
    print_json(payload)
    return 0


def command_start(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    b_id = current_branch(root)
    branch_payload: dict[str, Any] = {'branch_id': b_id}
    bdir = branch_dir(root, b_id)
    if (bdir / 'branch.json').exists():
        branch_payload.update({
            'branch_path': relpath(root, bdir),
            'branch': read_json(bdir / 'branch.json'),
            'objective_path': relpath(root, bdir / 'objective.md'),
            'context_path': relpath(root, bdir / 'context.md'),
        })
    else:
        branch_payload['error'] = 'current_branch points to missing branch'
    current_task = current_pointer(root, 'current_task')
    current_run = current_pointer(root, 'current_run')
    task_payload: dict[str, Any] = {}
    if current_task:
        tjson = task_json_path(root, current_task, branch_id=b_id)
        if tjson and tjson.exists():
            task = read_json(tjson)
            manifest_name = str(task.get('context_manifest', 'context_manifest.jsonl'))
            manifest_path = tjson.parent / manifest_name
            task_payload = {'task_id': current_task, 'task_path': relpath(root, tjson.parent), 'task': task, 'context_manifest_path': relpath(root, manifest_path), 'context_manifest': read_jsonl(manifest_path)}
        else:
            task_payload = {'task_id': current_task, 'error': 'current_task points to missing task or different branch'}
    run_payload: dict[str, Any] = {}
    if current_run:
        manifest_path = find_run_manifest(root, current_run, branch_id=b_id)
        if manifest_path:
            run_payload = {'run_id': current_run, 'run_path': relpath(root, manifest_path.parent), 'manifest_path': relpath(root, manifest_path), 'manifest': read_json(manifest_path)}
        else:
            run_payload = {'run_id': current_run, 'error': 'current_run points to missing run or different branch'}
    print_json({'root': root.as_posix(), 'initialized': True, 'entry_files': [name for name in ROOT_ENTRY_FILES if (root / name).exists()], 'workflow': relpath(root, project_os(root) / 'workflow.md'), 'current_session': current_session(root), 'runtime_focus_source': focus_payload(root).get('source'), 'current_branch': b_id, 'branch_context': branch_payload, 'current_task': current_task, 'current_run': current_run, 'task_context': task_payload, 'run_context': run_payload, 'next_step': 'Load branch/session context and required task context paths, then continue. Create a run before formal analysis if no current_run exists.'})
    return 0


def normalize_existing_index(root: Path, name: str) -> None:
    path = indexes_dir(root) / name
    if not path.exists():
        write_tsv(path, INDEX_HEADERS[name], [])
        return
    rows = read_tsv(path)
    write_tsv(path, INDEX_HEADERS[name], [{h: row.get(h, '') for h in INDEX_HEADERS[name]} for row in rows])


def command_refresh_indexes(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    refresh_branch_index(root)
    refresh_task_index(root)
    refresh_run_index(root)
    for name in ['results.tsv', 'assets.tsv', 'asset_locations.tsv', 'asset_usage.tsv', 'releases.tsv']:
        normalize_existing_index(root, name)
    sync_primary_locations_from_assets(root)
    refresh_asset_usage(root)
    refresh_results_index_markdown(root)
    data_assets_view = refresh_data_assets_markdown(root)
    append_event(root, 'state.updated', branch_id=current_branch(root), detail={'command': 'refresh-indexes'})
    print_json({'refreshed': list(INDEX_HEADERS) + ['RUNS_INDEX.tsv', 'RESULTS_INDEX.md', data_assets_view.get('path', 'DATA_ASSETS.md')], 'data_assets_view': data_assets_view})
    return 0


def command_create_branch(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    branch_id = args.branch_id or slugify(args.title)
    payload = create_branch_record(root, branch_id, args.title, parent_branch_id=args.parent_branch_id, git_branch=args.git_branch, notes=args.notes, set_current=args.set_current)
    print_json(payload)
    return 0


def command_set_current_branch(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    row = branch_row(root, args.branch_id)
    if not row:
        raise ProjectOSError(f'Missing branch: {args.branch_id}')
    if row.get('status') in {'archived', 'abandoned'}:
        raise ProjectOSError(f'Cannot set inactive branch current: {args.branch_id} status={row.get("status")}')
    warning = ''
    current_task = current_pointer(root, 'current_task')
    if current_task:
        tjson = task_json_path(root, current_task)
        if tjson and read_json(tjson).get('branch_id') != args.branch_id:
            warning = f'current_task belongs to another branch and was left unchanged: {current_task}'
    set_pointer(root, 'current_branch', args.branch_id)
    append_event(root, 'branch.changed', branch_id=args.branch_id, detail={'current_branch': args.branch_id, 'warning': warning})
    print_json({'current_branch': args.branch_id, 'warning': warning})
    return 0


def command_list_branches(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    refresh_branch_index(root)
    rows = read_tsv(indexes_dir(root) / 'branches.tsv')
    if args.status:
        rows = [r for r in rows if r.get('status') == args.status]
    print_json({'branches': rows, 'count': len(rows), 'current_branch': current_branch(root)})
    return 0


def command_show_branch(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    manifest = branch_manifest(root, args.branch_id)
    tasks = [r for r in read_tsv(indexes_dir(root) / 'tasks.tsv') if r.get('branch_id') == args.branch_id]
    runs = [r for r in read_tsv(indexes_dir(root) / 'runs.tsv') if r.get('branch_id') == args.branch_id]
    results = [r for r in read_tsv(indexes_dir(root) / 'results.tsv') if r.get('branch_id') == args.branch_id]
    print_json({'branch': manifest, 'counts': {'tasks': len(tasks), 'runs': len(runs), 'results': len(results)}})
    return 0


def command_archive_branch(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    manifest = branch_manifest(root, args.branch_id)
    manifest['status'] = args.status
    manifest['closed_at'] = now_iso()
    manifest['notes'] = args.notes or manifest.get('notes', '')
    write_json(branch_dir(root, args.branch_id) / 'branch.json', manifest)
    upsert_tsv(indexes_dir(root) / 'branches.tsv', INDEX_HEADERS['branches.tsv'], 'branch_id', branch_index_row(root, manifest))
    append_event(root, 'branch.archived', branch_id=args.branch_id, detail={'status': args.status, 'notes': args.notes})
    print_json({'archived_branch': args.branch_id, 'status': args.status})
    return 0
