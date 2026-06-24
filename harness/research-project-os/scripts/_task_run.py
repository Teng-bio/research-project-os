from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from _schema import *
from _paths import *
from _project_io import *
from _views import refresh_data_assets_markdown
from _assets import asset_usage_row, find_asset_row, looks_like_url, upsert_asset_usage


def ensure_initialized(root: Path) -> None:
    if not (project_os(root) / 'workflow.md').exists():
        raise ProjectOSError(f'Missing {OS_DIR}/workflow.md. Run init first.')


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


def task_json_path(root: Path, task_id: str, branch_id: str | None = None) -> Path | None:
    if branch_id:
        path = branch_task_dir(root, branch_id, task_id) / 'task.json'
        return path if path.exists() else None
    for row in read_tsv(indexes_dir(root) / 'tasks.tsv'):
        if row.get('task_id') == task_id:
            candidate = root / row.get('task_path', '') / 'task.json'
            if candidate.exists():
                return candidate
    for path in (project_os(root) / 'branches').glob(f'*/tasks/{task_id}/task.json'):
        if path.exists():
            return path
    legacy = project_os(root) / 'tasks' / task_id / 'task.json'
    return legacy if legacy.exists() else None


def task_dir(root: Path, task_id: str, branch_id: str | None = None) -> Path | None:
    path = task_json_path(root, task_id, branch_id=branch_id)
    return path.parent if path else None


def default_context_manifest() -> str:
    lines = [
        {'type': 'state', 'path': 'PROJECT_STATE.md', 'purpose': 'current project state', 'required': True},
        {'type': 'workflow', 'path': '.project_os/workflow.md', 'purpose': 'project workflow contract', 'required': True},
        {'type': 'data', 'path': 'DATA_ASSETS.md', 'purpose': 'human data/source view', 'required': False},
        {'type': 'result', 'path': 'RESULTS_INDEX.md', 'purpose': 'human-facing result index', 'required': False},
        {'type': 'decision', 'path': 'DECISIONS.md', 'purpose': 'durable decisions', 'required': False},
    ]
    return ''.join(json.dumps(line, ensure_ascii=False) + '\n' for line in lines)


def create_task_record(root: Path, title: str, kind: str = 'analysis', task_id: str = '', branch_id: str = '', parent_task_id: str | None = None, owner: str = '', stage: str = 'Intake', priority: str = 'normal', notes: str = '', set_current: bool = False) -> dict[str, Any]:
    branch_id = branch_id or current_branch(root)
    if not branch_row(root, branch_id):
        raise ProjectOSError(f'Missing branch: {branch_id}')
    if stage not in STAGES:
        raise ProjectOSError(f'Invalid stage: {stage}')
    created = now_iso()
    task_id = task_id or f"{datetime.now().strftime('%Y%m%d')}_{slugify(title)}"
    if task_json_path(root, task_id):
        raise ProjectOSError(f'Task already exists: {task_id}')
    tdir = branch_task_dir(root, branch_id, task_id)
    tdir.mkdir(parents=True)
    (tdir / 'research').mkdir()
    task = {
        'task_id': task_id, 'title': title, 'status': 'active', 'kind': kind, 'stage': stage, 'branch_id': branch_id, 'parent_task_id': parent_task_id, 'depends_on': {'tasks': [], 'results': []},
        'task_path': relpath(root, tdir), 'created_at': created, 'updated_at': created, 'owner': owner or '', 'priority': priority or 'normal', 'objective_file': 'objective.md', 'context_file': 'context.md', 'context_manifest': 'context_manifest.jsonl', 'handoff_file': 'handoff.md', 'notes': notes or '',
    }
    write_json(tdir / 'task.json', task)
    (tdir / 'objective.md').write_text(f'# Objective\n\n{title}\n', encoding='utf-8')
    (tdir / 'context.md').write_text('# Context\n\nAdd task-specific context here. Branch context is loaded separately.\n', encoding='utf-8')
    (tdir / 'context_manifest.jsonl').write_text(default_context_manifest(), encoding='utf-8')
    (tdir / 'decisions.md').write_text('# Decisions\n\n', encoding='utf-8')
    write_tsv(tdir / 'run_links.tsv', RUN_LINK_HEADERS, [])
    write_tsv(tdir / 'result_links.tsv', RESULT_LINK_HEADERS, [])
    (tdir / 'handoff.md').write_text('# Handoff\n\nCurrent handoff notes.\n', encoding='utf-8')
    upsert_tsv(indexes_dir(root) / 'tasks.tsv', INDEX_HEADERS['tasks.tsv'], 'task_id', task_index_row(root, task))
    if set_current:
        set_pointer(root, 'current_branch', branch_id)
        set_pointer(root, 'current_task', task_id)
    append_event(root, 'task.created', branch_id=branch_id, task_id=task_id, detail={'title': title, 'kind': kind, 'stage': stage})
    return {'created_task': task_id, 'branch_id': branch_id, 'path': relpath(root, tdir), 'set_current': bool(set_current)}


def task_index_row(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    return {h: task.get(h, '') for h in INDEX_HEADERS['tasks.tsv']}


def command_create_task(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    payload = create_task_record(root, args.title, args.kind, args.task_id, args.branch_id or current_branch(root), args.parent_task_id, args.owner, args.stage, args.priority, args.notes, args.set_current)
    print_json(payload); return 0


def command_set_current_task(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    tjson = task_json_path(root, args.task_id)
    if not tjson: raise ProjectOSError(f'Missing task: {args.task_id}')
    task = read_json(tjson)
    b_id = str(task.get('branch_id') or DEFAULT_BRANCH)
    set_pointer(root, 'current_branch', b_id); set_pointer(root, 'current_task', args.task_id)
    append_event(root, 'task.changed', branch_id=b_id, task_id=args.task_id, detail={'current_task': args.task_id})
    print_json({'current_branch': b_id, 'current_task': args.task_id}); return 0


def command_list_tasks(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root); refresh_task_index(root)
    rows = read_tsv(indexes_dir(root) / 'tasks.tsv')
    if args.branch_id: rows = [r for r in rows if r.get('branch_id') == args.branch_id]
    if args.status: rows = [r for r in rows if r.get('status') == args.status]
    if args.stage: rows = [r for r in rows if r.get('stage') == args.stage]
    print_json({'tasks': rows, 'count': len(rows)}); return 0


def command_show_task(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    tjson = task_json_path(root, args.task_id, branch_id=args.branch_id or None)
    if not tjson: raise ProjectOSError(f'Missing task: {args.task_id}')
    task = read_json(tjson); manifest_path = tjson.parent / task.get('context_manifest', 'context_manifest.jsonl')
    print_json({'task': task, 'task_path': relpath(root, tjson.parent), 'context_manifest_path': relpath(root, manifest_path), 'context_manifest': read_jsonl(manifest_path)}); return 0


def git_ref(root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(['git', '-C', root.as_posix(), 'rev-parse', 'HEAD'], text=True, capture_output=True, check=True).stdout.strip()
        status = subprocess.run(['git', '-C', root.as_posix(), 'status', '--porcelain'], text=True, capture_output=True, check=True).stdout.strip()
        return {'git_commit': commit, 'dirty': bool(status), 'git_available': True}
    except Exception:
        return {'git_commit': None, 'dirty': None, 'git_available': False}


def environment_snapshot() -> dict[str, Any]:
    return {
        'python': sys.executable,
        'python_version': sys.version.split()[0],
        'platform': platform.platform(),
        'conda_env': os.environ.get('CONDA_DEFAULT_ENV'),
        'virtual_env': os.environ.get('VIRTUAL_ENV'),
        'packages': {},
    }


def markdown_inline(value: Any) -> str:
    text = '' if value is None else str(value)
    return '`' + text.replace('`', '\\`') + '`'


def markdown_bullet_lines(items: list[str], *, empty: str = '- none') -> list[str]:
    return ['- ' + item for item in items] if items else [empty]


def environment_package_summary(env: dict[str, Any], *, limit: int = 25) -> tuple[list[str], list[str]]:
    capture = env.get('package_capture') if isinstance(env.get('package_capture'), dict) else {}
    packages = env.get('packages') if isinstance(env.get('packages'), dict) else {}
    summary = [
        f"- python: {markdown_inline(env.get('python', ''))}",
        f"- python_version: {markdown_inline(env.get('python_version', ''))}",
        f"- platform: {markdown_inline(env.get('platform', ''))}",
        f"- conda_env: {markdown_inline(env.get('conda_env', ''))}",
        f"- virtual_env: {markdown_inline(env.get('virtual_env', ''))}",
    ]
    if capture:
        summary.extend([
            f"- package_capture.method: {markdown_inline(capture.get('method', ''))}",
            f"- package_capture.count: {capture.get('count', 0)}",
            f"- package_capture.captured_at: {markdown_inline(capture.get('captured_at', ''))}",
        ])
        if capture.get('freeze_file'):
            summary.append(f"- package_capture.freeze_file: {markdown_inline(capture.get('freeze_file'))}")
        if capture.get('error'):
            summary.append(f"- package_capture.error: {markdown_inline(capture.get('error'))}")
        if capture.get('unparsed_count'):
            summary.append(f"- package_capture.unparsed_count: {capture.get('unparsed_count')}")
    package_lines: list[str] = []
    if packages:
        for name in sorted(packages)[:limit]:
            package_lines.append(f"{name}=={packages[name]}")
        if len(packages) > limit:
            package_lines.append(f"... {len(packages) - limit} more package(s); see captured freeze file or RUN_MANIFEST.json")
    return summary, package_lines


def run_summary_markdown(root: Path, manifest: dict[str, Any], manifest_path: Path) -> str:
    inputs = manifest.get('inputs', []) if isinstance(manifest.get('inputs'), list) else []
    commands = manifest.get('commands', []) if isinstance(manifest.get('commands'), list) else []
    outputs = manifest.get('outputs', []) if isinstance(manifest.get('outputs'), list) else []
    metrics = manifest.get('metrics', {}) if isinstance(manifest.get('metrics'), dict) else {}
    params = manifest.get('parameters', {}) if isinstance(manifest.get('parameters'), dict) else {}
    env = manifest.get('environment', {}) if isinstance(manifest.get('environment'), dict) else {}
    env_lines, package_lines = environment_package_summary(env)
    lines = [
        '# RUN_SUMMARY',
        '',
        '## Identity',
        '',
        f"- run_id: {markdown_inline(manifest.get('run_id', manifest_path.parent.name))}",
        f"- branch_id: {markdown_inline(manifest.get('branch_id', ''))}",
        f"- task_id: {markdown_inline(manifest.get('task_id', ''))}",
        f"- status: {markdown_inline(manifest.get('status', ''))}",
        f"- result_status: {markdown_inline(manifest.get('result_status', ''))}",
        f"- run_path: {markdown_inline(relpath(root, manifest_path.parent))}",
        f"- manifest: {markdown_inline(relpath(root, manifest_path))}",
        f"- created_at: {markdown_inline(manifest.get('created_at', ''))}",
        f"- closed_at: {markdown_inline(manifest.get('closed_at') or '')}",
        '',
        '## Counts',
        '',
        f"- inputs: {len(inputs)}",
        f"- parameters: {len(params)}",
        f"- commands: {len(commands)}",
        f"- outputs: {len(outputs)}",
        f"- metrics: {len(metrics)}",
        f"- promoted_to: {len(manifest.get('promoted_to', []) if isinstance(manifest.get('promoted_to'), list) else [])}",
        '',
        '## Parameters',
        '',
    ]
    lines.extend(markdown_bullet_lines([f"{key}: `{json.dumps(value, ensure_ascii=False)}`" for key, value in sorted(params.items())]))
    lines += ['', '## Inputs', '']
    lines.extend(markdown_bullet_lines([
        f"{item.get('name') or item.get('asset_id') or item.get('path') or '(unnamed)'}"
        f" | asset={markdown_inline(item.get('asset_id', ''))}"
        f" | path={markdown_inline(item.get('path', ''))}"
        f" | usage={markdown_inline(item.get('usage_kind', ''))}"
        for item in inputs if isinstance(item, dict)
    ]))
    lines += ['', '## Commands', '']
    lines.extend(markdown_bullet_lines([
        f"{idx}. exit={markdown_inline(item.get('exit_code', ''))} cwd={markdown_inline(item.get('cwd', ''))} command={markdown_inline(item.get('command', ''))}"
        for idx, item in enumerate([c for c in commands if isinstance(c, dict)], start=1)
    ]))
    lines += ['', '## Outputs', '']
    lines.extend(markdown_bullet_lines([
        f"{item.get('kind', 'artifact')} | path={markdown_inline(item.get('path', ''))} | result={markdown_inline(item.get('result_id', ''))} | asset={markdown_inline(item.get('asset_id', ''))}"
        for item in outputs if isinstance(item, dict)
    ]))
    lines += ['', '## Metrics', '']
    lines.extend(markdown_bullet_lines([
        f"{name}: value={markdown_inline(metric.get('value') if isinstance(metric, dict) else metric)}"
        + (f" unit={markdown_inline(metric.get('unit', ''))}" if isinstance(metric, dict) and metric.get('unit') else '')
        for name, metric in sorted(metrics.items())
    ]))
    promoted = manifest.get('promoted_to', []) if isinstance(manifest.get('promoted_to'), list) else []
    lines += ['', '## Promoted targets', '']
    lines.extend(markdown_bullet_lines([markdown_inline(item) for item in promoted]))
    lines += ['', '## Environment', '']
    lines.extend(env_lines)
    lines += ['', '## Package sample', '']
    lines.extend(markdown_bullet_lines([markdown_inline(item) for item in package_lines], empty='- no packages captured; run `capture-run-env --pip-freeze` if package provenance is needed'))
    lines += ['', '## Notes', '', str(manifest.get('notes') or '')]
    return '\n'.join(lines).rstrip() + '\n'


def command_create_run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    tjson = task_json_path(root, args.task_id)
    if not tjson: raise ProjectOSError(f'Missing task: {args.task_id}')
    task = read_json(tjson); branch_id = str(task.get('branch_id') or current_branch(root))
    run_id = args.run_id or f'{timestamp()}__{slugify(args.slug)}'
    if find_run_manifest(root, run_id): raise ProjectOSError(f'Run already exists: {run_id}')
    rdir = run_dir(root, branch_id, run_id, args.run_root)
    for subdir in ['', 'inputs', 'outputs', 'plots', 'tables', 'scripts', 'logs', 'docs']:
        (rdir / subdir).mkdir(parents=True, exist_ok=True)
    manifest = {'run_id': run_id, 'branch_id': branch_id, 'task_id': args.task_id, 'status': 'active', 'created_at': now_iso(), 'closed_at': None, 'code_ref': git_ref(root), 'environment': environment_snapshot(), 'inputs': [], 'parameters': {}, 'commands': [], 'outputs': [], 'metrics': {}, 'result_status': 'draft', 'promoted_to': [], 'notes': args.notes or ''}
    write_json(rdir / 'RUN_MANIFEST.json', manifest)
    task['updated_at'] = now_iso(); write_json(tjson, task)
    upsert_tsv(tjson.parent / 'run_links.tsv', RUN_LINK_HEADERS, 'run_id', {'run_id': run_id, 'branch_id': branch_id, 'status': 'active', 'path': relpath(root, rdir / 'RUN_MANIFEST.json'), 'created_at': manifest['created_at'], 'notes': args.notes or ''})
    set_pointer(root, 'current_branch', branch_id); set_pointer(root, 'current_task', args.task_id); set_pointer(root, 'current_run', run_id)
    upsert_tsv(indexes_dir(root) / 'runs.tsv', INDEX_HEADERS['runs.tsv'], 'run_id', run_index_row(root, manifest, rdir))
    write_tsv(root / 'RUNS_INDEX.tsv', ROOT_RUNS_HEADERS, read_tsv(indexes_dir(root) / 'runs.tsv'))
    append_event(root, 'run.created', branch_id=branch_id, task_id=args.task_id, run_id=run_id, detail={'run_path': relpath(root, rdir)})
    print_json({'created_run': run_id, 'branch_id': branch_id, 'task_id': args.task_id, 'path': relpath(root, rdir), 'current_run': run_id}); return 0


def run_index_row(root: Path, manifest: dict[str, Any], rdir: Path) -> dict[str, Any]:
    return {'run_id': manifest.get('run_id', rdir.name), 'branch_id': manifest.get('branch_id', ''), 'task_id': manifest.get('task_id', ''), 'status': manifest.get('status', ''), 'result_status': manifest.get('result_status', ''), 'run_path': relpath(root, rdir), 'created_at': manifest.get('created_at', ''), 'closed_at': manifest.get('closed_at') or '', 'code_ref': json.dumps(manifest.get('code_ref', {}), ensure_ascii=False, separators=(',', ':')), 'notes': manifest.get('notes', '')}


def find_run_manifest(root: Path, run_id: str, branch_id: str | None = None) -> Path | None:
    if branch_id:
        for run_root in ['runs', 'analysis_runs']:
            candidate = run_dir(root, branch_id, run_id, run_root) / 'RUN_MANIFEST.json'
            if candidate.exists(): return candidate
    for row in read_tsv(indexes_dir(root) / 'runs.tsv'):
        if row.get('run_id') == run_id:
            candidate = root / row.get('run_path', '') / 'RUN_MANIFEST.json'
            if candidate.exists(): return candidate
    for base in [root / 'runs', root / 'analysis_runs']:
        if not base.exists(): continue
        for pattern in ['*/*/RUN_MANIFEST.json', '*/RUN_MANIFEST.json']:
            for path in base.glob(pattern):
                try: data = read_json(path)
                except ProjectOSError: continue
                if data.get('run_id') == run_id and (not branch_id or data.get('branch_id') == branch_id): return path
    return None


def command_set_current_run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    manifest_path = find_run_manifest(root, args.run_id)
    if not manifest_path: raise ProjectOSError(f'Missing run: {args.run_id}')
    manifest = read_json(manifest_path); b_id = str(manifest.get('branch_id') or current_branch(root)); task_id = str(manifest.get('task_id') or '')
    set_pointer(root, 'current_branch', b_id)
    if task_id: set_pointer(root, 'current_task', task_id)
    set_pointer(root, 'current_run', args.run_id)
    append_event(root, 'run.updated', branch_id=b_id, task_id=task_id, run_id=args.run_id, detail={'current_run': args.run_id})
    print_json({'current_branch': b_id, 'current_task': task_id, 'current_run': args.run_id}); return 0


def command_close_run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    if args.status not in RUN_STATUSES: raise ProjectOSError(f'Invalid run status: {args.status}')
    manifest_path = find_run_manifest(root, args.run_id)
    if not manifest_path: raise ProjectOSError(f'Missing run: {args.run_id}')
    manifest = read_json(manifest_path); manifest['status'] = args.status; manifest['closed_at'] = now_iso()
    manifest['environment'] = {**environment_snapshot(), **(manifest.get('environment') if isinstance(manifest.get('environment'), dict) else {})}
    if args.notes: manifest['notes'] = args.notes
    manifest['summary_file'] = 'RUN_SUMMARY.md'
    write_json(manifest_path, manifest); refresh_run_index(root)
    (manifest_path.parent / 'RUN_SUMMARY.md').write_text(run_summary_markdown(root, manifest, manifest_path), encoding='utf-8')
    append_event(root, 'run.closed', branch_id=str(manifest.get('branch_id', '')), task_id=str(manifest.get('task_id', '')), run_id=args.run_id, detail={'status': args.status})
    print_json({'closed_run': args.run_id, 'status': args.status, 'manifest': relpath(root, manifest_path), 'summary': relpath(root, manifest_path.parent / 'RUN_SUMMARY.md')}); return 0


def command_list_runs(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root); refresh_run_index(root)
    rows = read_tsv(indexes_dir(root) / 'runs.tsv')
    if args.branch_id: rows = [r for r in rows if r.get('branch_id') == args.branch_id]
    if args.task_id: rows = [r for r in rows if r.get('task_id') == args.task_id]
    if args.status: rows = [r for r in rows if r.get('status') == args.status]
    print_json({'runs': rows, 'count': len(rows)}); return 0


def command_show_run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    manifest_path = find_run_manifest(root, args.run_id, args.branch_id or None)
    if not manifest_path: raise ProjectOSError(f'Missing run: {args.run_id}')
    print_json({'run_id': args.run_id, 'run_path': relpath(root, manifest_path.parent), 'manifest_path': relpath(root, manifest_path), 'manifest': read_json(manifest_path)}); return 0


def add_run_input(root: Path, run_id: str, *, asset_id: str = '', path: str = '', name: str = '', usage_kind: str = 'input', notes: str = '', append_event_flag: bool = True) -> dict[str, Any]:
    manifest_path = find_run_manifest(root, run_id)
    if not manifest_path: raise ProjectOSError(f'Missing run: {run_id}')
    if asset_id and not find_asset_row(root, asset_id): raise ProjectOSError(f'Missing asset: {asset_id}')
    manifest = read_json(manifest_path)
    branch_id = str(manifest.get('branch_id') or current_branch(root)); task_id = str(manifest.get('task_id') or '')
    stored_path = path
    if path and not looks_like_url(path):
        _, stored_path = project_relative_or_absolute(root, path)
    entry = {'name': name or asset_id or Path(stored_path).name, 'asset_id': asset_id, 'path': stored_path, 'usage_kind': usage_kind, 'registered_at': now_iso(), 'notes': notes}
    manifest.setdefault('inputs', []).append(entry)
    write_json(manifest_path, manifest)
    usage: dict[str, Any] = {}
    if asset_id:
        usage = asset_usage_row(asset_id, branch_id=branch_id, task_id=task_id, run_id=run_id, usage_kind=usage_kind, notes=notes)
        upsert_asset_usage(root, usage)
        refresh_data_assets_markdown(root)
    if append_event_flag:
        append_event(root, 'run.updated', branch_id=branch_id, task_id=task_id, run_id=run_id, detail={'action': 'add-run-input', 'asset_id': asset_id, 'path': stored_path})
    return {'branch_id': branch_id, 'task_id': task_id, 'run_id': run_id, 'input': entry, 'usage': usage}


def command_add_run_input(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    if not args.asset_id and not args.path: raise ProjectOSError('add-run-input requires --asset-id or --path')
    print_json(add_run_input(root, args.run_id, asset_id=args.asset_id, path=args.path, name=args.name, usage_kind=args.usage_kind, notes=args.notes)); return 0


def command_add_run_command(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    manifest_path = find_run_manifest(root, args.run_id)
    if not manifest_path: raise ProjectOSError(f'Missing run: {args.run_id}')
    manifest = read_json(manifest_path)
    entry = {'command': args.command, 'cwd': args.cwd or '', 'exit_code': args.exit_code, 'recorded_at': now_iso(), 'notes': args.notes or ''}
    manifest.setdefault('commands', []).append(entry); write_json(manifest_path, manifest)
    append_event(root, 'run.updated', branch_id=str(manifest.get('branch_id', '')), task_id=str(manifest.get('task_id', '')), run_id=args.run_id, detail={'action': 'add-run-command'})
    print_json({'run_id': args.run_id, 'command': entry}); return 0


def command_add_run_output(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    manifest_path = find_run_manifest(root, args.run_id)
    if not manifest_path: raise ProjectOSError(f'Missing run: {args.run_id}')
    if args.asset_id and not find_asset_row(root, args.asset_id):
        raise ProjectOSError(f'Missing asset: {args.asset_id}')
    manifest = read_json(manifest_path)
    _, stored_path = project_relative_or_absolute(root, args.path)
    entry = {'path': stored_path, 'kind': args.kind, 'result_id': args.result_id or '', 'asset_id': args.asset_id or '', 'recorded_at': now_iso(), 'notes': args.notes or ''}
    manifest.setdefault('outputs', []).append(entry); write_json(manifest_path, manifest)
    if args.asset_id:
        upsert_asset_usage(root, asset_usage_row(args.asset_id, branch_id=str(manifest.get('branch_id', '')), task_id=str(manifest.get('task_id', '')), run_id=args.run_id, result_id=args.result_id or '', usage_kind='output', notes=args.notes or ''))
        refresh_data_assets_markdown(root)
    append_event(root, 'run.updated', branch_id=str(manifest.get('branch_id', '')), task_id=str(manifest.get('task_id', '')), run_id=args.run_id, detail={'action': 'add-run-output', 'path': stored_path})
    print_json({'run_id': args.run_id, 'output': entry}); return 0


def parse_metric_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return raw


def parse_key_value(raw: str) -> tuple[str, Any]:
    if '=' not in raw:
        raise ProjectOSError(f'Expected key=value: {raw}')
    key, value = raw.split('=', 1)
    key = key.strip()
    if not key:
        raise ProjectOSError(f'Empty key in key=value: {raw}')
    return key, parse_metric_value(value.strip())


def command_add_run_parameter(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    manifest_path = find_run_manifest(root, args.run_id)
    if not manifest_path: raise ProjectOSError(f'Missing run: {args.run_id}')
    manifest = read_json(manifest_path)
    params = manifest.setdefault('parameters', {})
    if not isinstance(params, dict):
        params = {}; manifest['parameters'] = params
    changed: dict[str, Any] = {}
    for item in args.param:
        key, value = parse_key_value(item)
        params[key] = value
        changed[key] = value
    write_json(manifest_path, manifest)
    append_event(root, 'run.updated', branch_id=str(manifest.get('branch_id', '')), task_id=str(manifest.get('task_id', '')), run_id=args.run_id, detail={'action': 'add-run-parameter', 'keys': sorted(changed)})
    print_json({'run_id': args.run_id, 'parameters': params, 'changed': changed}); return 0


def command_capture_run_env(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    manifest_path = find_run_manifest(root, args.run_id)
    if not manifest_path: raise ProjectOSError(f'Missing run: {args.run_id}')
    manifest = read_json(manifest_path)
    env = environment_snapshot()
    packages: dict[str, str] = {}
    if args.pip_freeze:
        try:
            proc = subprocess.run([sys.executable, '-m', 'pip', 'freeze'], text=True, capture_output=True, check=True, timeout=30)
            lines = [line for line in proc.stdout.splitlines() if line.strip()]
            freeze_rel = args.freeze_file or 'docs/pip-freeze.txt'
            freeze_path = manifest_path.parent / freeze_rel
            freeze_path.parent.mkdir(parents=True, exist_ok=True)
            freeze_path.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
            unparsed: list[str] = []
            for line in proc.stdout.splitlines():
                if '==' in line:
                    name, version = line.split('==', 1)
                    packages[name] = version
                elif line.strip():
                    unparsed.append(line.strip())
            env['packages'] = packages
            env['package_capture'] = {
                'method': 'pip freeze',
                'count': len(packages),
                'raw_line_count': len(lines),
                'unparsed_count': len(unparsed),
                'unparsed_examples': unparsed[:10],
                'freeze_file': relpath(root, freeze_path),
                'captured_at': now_iso(),
            }
        except Exception as exc:
            env['package_capture'] = {'method': 'pip freeze', 'error': str(exc), 'captured_at': now_iso()}
    old_env = manifest.get('environment') if isinstance(manifest.get('environment'), dict) else {}
    manifest['environment'] = {**old_env, **env}
    write_json(manifest_path, manifest)
    detail = {'action': 'capture-run-env', 'packages': len(packages)}
    if isinstance(manifest.get('environment'), dict) and isinstance(manifest['environment'].get('package_capture'), dict):
        detail['freeze_file'] = manifest['environment']['package_capture'].get('freeze_file', '')
    append_event(root, 'run.updated', branch_id=str(manifest.get('branch_id', '')), task_id=str(manifest.get('task_id', '')), run_id=args.run_id, detail=detail)
    print_json({'run_id': args.run_id, 'environment': manifest['environment']}); return 0


def command_add_run_metric(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    manifest_path = find_run_manifest(root, args.run_id)
    if not manifest_path: raise ProjectOSError(f'Missing run: {args.run_id}')
    manifest = read_json(manifest_path)
    metric = {'value': parse_metric_value(args.value), 'unit': args.unit or '', 'recorded_at': now_iso(), 'notes': args.notes or ''}
    manifest.setdefault('metrics', {})[args.name] = metric; write_json(manifest_path, manifest)
    append_event(root, 'run.updated', branch_id=str(manifest.get('branch_id', '')), task_id=str(manifest.get('task_id', '')), run_id=args.run_id, detail={'action': 'add-run-metric', 'name': args.name})
    print_json({'run_id': args.run_id, 'metric': {args.name: metric}}); return 0


def command_update_task_stage(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    if args.stage not in STAGES: raise ProjectOSError(f'Invalid stage: {args.stage}')
    tjson = task_json_path(root, args.task_id, branch_id=args.branch_id or None)
    if not tjson: raise ProjectOSError(f'Missing task: {args.task_id}')
    task = read_json(tjson); task['stage'] = args.stage; task['updated_at'] = now_iso()
    if args.status:
        if args.status not in TASK_STATUSES: raise ProjectOSError(f'Invalid task status: {args.status}')
        task['status'] = args.status
    if args.notes:
        task['notes'] = (task.get('notes', '') + '; ' + args.notes).strip('; ')
    write_json(tjson, task); upsert_tsv(indexes_dir(root) / 'tasks.tsv', INDEX_HEADERS['tasks.tsv'], 'task_id', task_index_row(root, task))
    append_event(root, 'task.changed', branch_id=str(task.get('branch_id', '')), task_id=args.task_id, detail={'stage': args.stage, 'status': task.get('status', '')})
    print_json({'updated_task': args.task_id, 'stage': args.stage, 'status': task.get('status', '')}); return 0


def command_update_task(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    tjson = task_json_path(root, args.task_id, branch_id=args.branch_id or None)
    if not tjson: raise ProjectOSError(f'Missing task: {args.task_id}')
    task = read_json(tjson)
    changed: dict[str, Any] = {}
    if args.title:
        task['title'] = args.title; changed['title'] = args.title
    if args.kind:
        task['kind'] = args.kind; changed['kind'] = args.kind
    if args.owner is not None:
        task['owner'] = args.owner; changed['owner'] = args.owner
    if args.priority is not None:
        task['priority'] = args.priority; changed['priority'] = args.priority
    if args.status:
        if args.status not in TASK_STATUSES: raise ProjectOSError(f'Invalid task status: {args.status}')
        task['status'] = args.status; changed['status'] = args.status
    if args.notes:
        task['notes'] = (task.get('notes', '') + '; ' + args.notes).strip('; '); changed['notes'] = args.notes
    task['updated_at'] = now_iso()
    write_json(tjson, task); upsert_tsv(indexes_dir(root) / 'tasks.tsv', INDEX_HEADERS['tasks.tsv'], 'task_id', task_index_row(root, task))
    append_event(root, 'task.changed', branch_id=str(task.get('branch_id', '')), task_id=args.task_id, detail={'action': 'update-task', 'changed': changed})
    print_json({'updated_task': args.task_id, 'changed': changed, 'task': task}); return 0


def command_add_dependency(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    tjson = task_json_path(root, args.task_id, branch_id=args.branch_id or None)
    if not tjson: raise ProjectOSError(f'Missing task: {args.task_id}')
    task = read_json(tjson); depends_on = task.setdefault('depends_on', {'tasks': [], 'results': []})
    if not isinstance(depends_on, dict):
        depends_on = {'tasks': [], 'results': []}; task['depends_on'] = depends_on
    depends_on.setdefault('tasks', []); depends_on.setdefault('results', [])
    added: dict[str, list[str]] = {'tasks': [], 'results': []}
    for dep_task in args.depends_on_task:
        if dep_task == args.task_id: raise ProjectOSError('Task cannot depend on itself')
        if not task_json_path(root, dep_task): raise ProjectOSError(f'Missing dependency task: {dep_task}')
        if dep_task not in depends_on['tasks']:
            depends_on['tasks'].append(dep_task); added['tasks'].append(dep_task)
    result_ids = {r.get('result_id', '') for r in read_tsv(indexes_dir(root) / 'results.tsv')}
    for dep_result in args.depends_on_result:
        if dep_result not in result_ids: raise ProjectOSError(f'Missing dependency result: {dep_result}')
        if dep_result not in depends_on['results']:
            depends_on['results'].append(dep_result); added['results'].append(dep_result)
    task['updated_at'] = now_iso()
    write_json(tjson, task); upsert_tsv(indexes_dir(root) / 'tasks.tsv', INDEX_HEADERS['tasks.tsv'], 'task_id', task_index_row(root, task))
    append_event(root, 'task.changed', branch_id=str(task.get('branch_id', '')), task_id=args.task_id, detail={'action': 'add-dependency', 'added': added})
    print_json({'task_id': args.task_id, 'depends_on': depends_on, 'added': added}); return 0


def command_remove_dependency(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    tjson = task_json_path(root, args.task_id, branch_id=args.branch_id or None)
    if not tjson: raise ProjectOSError(f'Missing task: {args.task_id}')
    task = read_json(tjson); depends_on = task.setdefault('depends_on', {'tasks': [], 'results': []})
    if not isinstance(depends_on, dict):
        depends_on = {'tasks': [], 'results': []}; task['depends_on'] = depends_on
    removed: dict[str, list[str]] = {'tasks': [], 'results': []}
    for dep_task in args.depends_on_task:
        if dep_task in depends_on.get('tasks', []):
            depends_on['tasks'] = [x for x in depends_on.get('tasks', []) if x != dep_task]; removed['tasks'].append(dep_task)
    for dep_result in args.depends_on_result:
        if dep_result in depends_on.get('results', []):
            depends_on['results'] = [x for x in depends_on.get('results', []) if x != dep_result]; removed['results'].append(dep_result)
    task['updated_at'] = now_iso()
    write_json(tjson, task); upsert_tsv(indexes_dir(root) / 'tasks.tsv', INDEX_HEADERS['tasks.tsv'], 'task_id', task_index_row(root, task))
    append_event(root, 'task.changed', branch_id=str(task.get('branch_id', '')), task_id=args.task_id, detail={'action': 'remove-dependency', 'removed': removed})
    print_json({'task_id': args.task_id, 'depends_on': depends_on, 'removed': removed}); return 0


def command_close_task(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    if args.status not in TASK_STATUSES: raise ProjectOSError(f'Invalid task status: {args.status}')
    tjson = task_json_path(root, args.task_id, branch_id=args.branch_id or None)
    if not tjson: raise ProjectOSError(f'Missing task: {args.task_id}')
    task = read_json(tjson); task['status'] = args.status; task['updated_at'] = now_iso(); task['closed_at'] = now_iso()
    if args.notes: task['notes'] = (task.get('notes', '') + '; ' + args.notes).strip('; ')
    write_json(tjson, task); upsert_tsv(indexes_dir(root) / 'tasks.tsv', INDEX_HEADERS['tasks.tsv'], 'task_id', task_index_row(root, task))
    append_event(root, 'task.closed', branch_id=str(task.get('branch_id', '')), task_id=args.task_id, detail={'status': args.status, 'notes': args.notes or ''})
    print_json({'closed_task': args.task_id, 'status': args.status}); return 0


def command_add_context(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    tjson = task_json_path(root, args.task_id, branch_id=args.branch_id or None)
    if not tjson: raise ProjectOSError(f'Missing task: {args.task_id}')
    task = read_json(tjson); manifest_path = tjson.parent / task.get('context_manifest', 'context_manifest.jsonl')
    raw_path = args.path
    target = Path(raw_path) if Path(raw_path).is_absolute() else root / raw_path
    if args.required and not target.exists(): raise ProjectOSError(f'Required context path missing: {raw_path}')
    entry = {'type': args.type, 'path': raw_path, 'purpose': args.purpose, 'required': bool(args.required)}
    existing = read_jsonl(manifest_path)
    if any(item.get('path') == raw_path for item in existing):
        raise ProjectOSError(f'Context path already present: {raw_path}')
    with manifest_path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
    task['updated_at'] = now_iso(); write_json(tjson, task)
    append_event(root, 'task.changed', branch_id=str(task.get('branch_id', '')), task_id=args.task_id, detail={'action': 'add-context', 'path': raw_path})
    print_json({'added_context': entry, 'task_id': args.task_id, 'context_manifest': relpath(root, manifest_path)}); return 0


def command_remove_context(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    tjson = task_json_path(root, args.task_id, branch_id=args.branch_id or None)
    if not tjson: raise ProjectOSError(f'Missing task: {args.task_id}')
    task = read_json(tjson); manifest_path = tjson.parent / task.get('context_manifest', 'context_manifest.jsonl')
    rows = read_jsonl(manifest_path)
    kept = [r for r in rows if r.get('path') != args.path]
    if len(kept) == len(rows): raise ProjectOSError(f'Context path not found: {args.path}')
    manifest_path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in kept), encoding='utf-8')
    task['updated_at'] = now_iso(); write_json(tjson, task)
    append_event(root, 'task.changed', branch_id=str(task.get('branch_id', '')), task_id=args.task_id, detail={'action': 'remove-context', 'path': args.path})
    print_json({'removed_context': args.path, 'task_id': args.task_id, 'context_manifest': relpath(root, manifest_path)}); return 0


def command_update_run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    manifest_path = find_run_manifest(root, args.run_id, branch_id=args.branch_id or None)
    if not manifest_path: raise ProjectOSError(f'Missing run: {args.run_id}')
    manifest = read_json(manifest_path)
    if args.status:
        if args.status not in RUN_STATUSES: raise ProjectOSError(f'Invalid run status: {args.status}')
        manifest['status'] = args.status
        if args.status in {'completed', 'failed', 'pending_review', 'archived', 'superseded'} and not manifest.get('closed_at'):
            manifest['closed_at'] = now_iso()
    if args.result_status:
        if args.result_status not in RESULT_STATUSES: raise ProjectOSError(f'Invalid result status: {args.result_status}')
        manifest['result_status'] = args.result_status
    if args.notes:
        manifest['notes'] = (manifest.get('notes', '') + '; ' + args.notes).strip('; ')
    write_json(manifest_path, manifest); refresh_run_index(root)
    append_event(root, 'run.updated', branch_id=str(manifest.get('branch_id', '')), task_id=str(manifest.get('task_id', '')), run_id=args.run_id, detail={'status': manifest.get('status', ''), 'result_status': manifest.get('result_status', '')})
    print_json({'updated_run': args.run_id, 'manifest': relpath(root, manifest_path), 'status': manifest.get('status', ''), 'result_status': manifest.get('result_status', '')}); return 0


def refresh_task_index(root: Path) -> None:
    rows: list[dict[str, Any]] = []
    seen_task_ids: set[str] = set()
    for task_file in sorted((project_os(root) / 'branches').glob('*/tasks/*/task.json')):
        task = read_json(task_file)
        if task.get('task_id'):
            seen_task_ids.add(str(task.get('task_id')))
        rows.append(task_index_row(root, task))
    legacy = project_os(root) / 'tasks'
    if legacy.exists():
        for task_file in sorted(legacy.glob('*/task.json')):
            task = read_json(task_file)
            if str(task.get('task_id') or task_file.parent.name) in seen_task_ids:
                continue
            task.setdefault('branch_id', DEFAULT_BRANCH); task.setdefault('task_path', relpath(root, task_file.parent)); rows.append(task_index_row(root, task))
    write_tsv(indexes_dir(root) / 'tasks.tsv', INDEX_HEADERS['tasks.tsv'], rows)


def refresh_run_index(root: Path) -> None:
    rows: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    for run_root in [root / 'runs', root / 'analysis_runs']:
        if not run_root.exists(): continue
        for pattern in ['*/*/RUN_MANIFEST.json', '*/RUN_MANIFEST.json']:
            for manifest_file in sorted(run_root.glob(pattern)):
                manifest = read_json(manifest_file)
                if 'branch_id' not in manifest:
                    manifest['branch_id'] = manifest_file.parent.parent.name if manifest_file.parent.parent != run_root else DEFAULT_BRANCH
                run_id = str(manifest.get('run_id') or manifest_file.parent.name)
                if run_id in seen_run_ids:
                    continue
                seen_run_ids.add(run_id)
                rows.append(run_index_row(root, manifest, manifest_file.parent))
    write_tsv(indexes_dir(root) / 'runs.tsv', INDEX_HEADERS['runs.tsv'], rows); write_tsv(root / 'RUNS_INDEX.tsv', ROOT_RUNS_HEADERS, rows)
