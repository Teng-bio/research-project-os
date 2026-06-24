from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path
from typing import Any

from _schema import *
from _paths import *
from _project_io import *
from _views import refresh_data_assets_markdown, refresh_results_index_markdown
from _assets import refresh_asset_usage
from _project_branch import branch_row, create_branch_record, ensure_initialized, project_json_payload, refresh_branch_index
from _task_run import default_context_manifest, environment_snapshot, refresh_run_index, refresh_task_index


def tsv_header(path: Path) -> list[str]:
    first = path.read_text(encoding='utf-8', errors='replace').splitlines()[:1] if path.exists() else []
    return first[0].split('\t') if first else []


def infer_task_id_for_run_from_links(root: Path, run_id: str, branch_id: str = '') -> str:
    candidates: set[str] = set()
    search_roots: list[Path] = []
    if branch_id:
        search_roots.append(branch_dir(root, branch_id) / 'tasks')
    search_roots.extend([project_os(root) / 'branches', project_os(root) / 'tasks'])
    for base in search_roots:
        if not base.exists():
            continue
        task_dirs = sorted(base.glob('*/tasks/*')) if base.name == 'branches' else sorted(base.glob('*'))
        for tdir in task_dirs:
            links = tdir / 'run_links.tsv'
            if not links.exists():
                continue
            for row in read_tsv(links):
                if row.get('run_id') == run_id:
                    task_id = tdir.name
                    tjson = tdir / 'task.json'
                    if tjson.exists():
                        try:
                            task_id = str(read_json(tjson).get('task_id') or task_id)
                        except ProjectOSError:
                            pass
                    candidates.add(task_id)
    return next(iter(candidates)) if len(candidates) == 1 else ''


def infer_task_id_for_result_from_links(root: Path, result_id: str, branch_id: str = '') -> str:
    candidates: set[str] = set()
    bases = [project_os(root) / 'branches']
    if branch_id:
        bases.insert(0, branch_dir(root, branch_id) / 'tasks')
    bases.append(project_os(root) / 'tasks')
    for base in bases:
        if not base.exists():
            continue
        task_dirs = sorted(base.glob('*/tasks/*')) if base.name == 'branches' else sorted(base.glob('*'))
        for tdir in task_dirs:
            links = tdir / 'result_links.tsv'
            if not links.exists():
                continue
            for row in read_tsv(links):
                if row.get('result_id') == result_id:
                    task_id = tdir.name
                    tjson = tdir / 'task.json'
                    if tjson.exists():
                        try:
                            task_id = str(read_json(tjson).get('task_id') or task_id)
                        except ProjectOSError:
                            pass
                    candidates.add(task_id)
    return next(iter(candidates)) if len(candidates) == 1 else ''


def infer_run_id_for_result_from_links(root: Path, result_id: str, branch_id: str = '') -> str:
    candidates: set[str] = set()
    bases = [project_os(root) / 'branches']
    if branch_id:
        bases.insert(0, branch_dir(root, branch_id) / 'tasks')
    bases.append(project_os(root) / 'tasks')
    for base in bases:
        if not base.exists():
            continue
        task_dirs = sorted(base.glob('*/tasks/*')) if base.name == 'branches' else sorted(base.glob('*'))
        for tdir in task_dirs:
            links = tdir / 'result_links.tsv'
            if not links.exists():
                continue
            for row in read_tsv(links):
                if row.get('result_id') == result_id and row.get('run_id'):
                    candidates.add(str(row.get('run_id')))
    return next(iter(candidates)) if len(candidates) == 1 else ''


def infer_run_id_from_result_path(root: Path, raw_path: str, branch_id: str = '') -> str:
    if not raw_path:
        return ''
    path = Path(raw_path)
    parts = path.parts
    for run_root in ['runs', 'analysis_runs']:
        if run_root not in parts:
            continue
        idx = parts.index(run_root)
        if len(parts) <= idx + 1:
            continue
        first = parts[idx + 1]
        second = parts[idx + 2] if len(parts) > idx + 2 else ''
        if second and (root / run_root / first / second / 'RUN_MANIFEST.json').exists():
            return second
        if (root / run_root / first / 'RUN_MANIFEST.json').exists():
            return first
        if branch_id and first == branch_id and second:
            return second
        return first
    return ''


def normalize_task_link_tables(root: Path, tdir: Path, branch_id: str) -> None:
    if not (tdir / 'run_links.tsv').exists():
        write_tsv(tdir / 'run_links.tsv', RUN_LINK_HEADERS, [])
    else:
        run_rows = []
        for row in read_tsv(tdir / 'run_links.tsv'):
            item = {h: row.get(h, '') for h in RUN_LINK_HEADERS}
            item['branch_id'] = item.get('branch_id') or branch_id
            run_rows.append(item)
        write_tsv(tdir / 'run_links.tsv', RUN_LINK_HEADERS, run_rows)
    if not (tdir / 'result_links.tsv').exists():
        write_tsv(tdir / 'result_links.tsv', RESULT_LINK_HEADERS, [])
    else:
        result_rows = []
        for row in read_tsv(tdir / 'result_links.tsv'):
            item = {h: row.get(h, '') for h in RESULT_LINK_HEADERS}
            item['branch_id'] = item.get('branch_id') or branch_id
            result_rows.append(item)
        write_tsv(tdir / 'result_links.tsv', RESULT_LINK_HEADERS, result_rows)


def legacy_pathish(raw: Any) -> str:
    if raw is None:
        return ''
    text = str(raw).strip()
    if not text:
        return ''
    if looks_like_url(text) or '/' in text or '\\' in text or text.startswith(('./', '../')):
        return text
    return ''


def normalize_legacy_input_entry(name: str, value: Any, created_at: str, *, notes: str = '') -> dict[str, Any]:
    path = legacy_pathish(value)
    entry: dict[str, Any] = {
        'name': name or (Path(path).name if path else 'legacy_input'),
        'asset_id': '',
        'path': path,
        'usage_kind': 'input',
        'registered_at': created_at,
        'notes': notes or 'migrated legacy input',
    }
    if not path:
        entry['value'] = value
    return entry


def normalize_legacy_output_entry(name: str, value: Any, created_at: str, *, kind: str = 'artifact', notes: str = '') -> dict[str, Any]:
    path = legacy_pathish(value)
    entry: dict[str, Any] = {
        'name': name or (Path(path).name if path else 'legacy_output'),
        'path': path,
        'kind': kind or 'artifact',
        'result_id': '',
        'asset_id': '',
        'recorded_at': created_at,
        'notes': notes or 'migrated legacy output',
    }
    if not path:
        entry['value'] = value
    return entry


def normalize_legacy_inputs(raw: Any, created_at: str) -> list[dict[str, Any]]:
    if raw is None or raw == '':
        return []
    if isinstance(raw, list):
        entries: list[dict[str, Any]] = []
        for idx, item in enumerate(raw, start=1):
            if isinstance(item, dict):
                entries.append(item)
            else:
                entries.append(normalize_legacy_input_entry(f'legacy_input_{idx}', item, created_at, notes='migrated legacy scalar input'))
        return entries
    if isinstance(raw, dict):
        entries = []
        for key, value in raw.items():
            if isinstance(value, list):
                for idx, item in enumerate(value, start=1):
                    entries.append(normalize_legacy_input_entry(f'{key}_{idx}', item, created_at, notes=f'migrated legacy input field: {key}'))
            else:
                entries.append(normalize_legacy_input_entry(str(key), value, created_at, notes=f'migrated legacy input field: {key}'))
        return entries
    return [normalize_legacy_input_entry('legacy_inputs', raw, created_at)]


def normalize_legacy_outputs(raw: Any, created_at: str) -> list[dict[str, Any]]:
    if raw is None or raw == '':
        return []
    if isinstance(raw, list):
        entries: list[dict[str, Any]] = []
        for idx, item in enumerate(raw, start=1):
            if isinstance(item, dict):
                entries.append(item)
            else:
                entries.append(normalize_legacy_output_entry(f'legacy_output_{idx}', item, created_at, notes='migrated legacy scalar output'))
        return entries
    if isinstance(raw, dict):
        entries = []
        for key, value in raw.items():
            output_kind = 'document' if key in {'document', 'documents', 'report', 'reports'} else 'artifact'
            if isinstance(value, list):
                for idx, item in enumerate(value, start=1):
                    entries.append(normalize_legacy_output_entry(f'{key}_{idx}', item, created_at, kind=output_kind, notes=f'migrated legacy output field: {key}'))
            else:
                entries.append(normalize_legacy_output_entry(str(key), value, created_at, kind=output_kind, notes=f'migrated legacy output field: {key}'))
        return entries
    return [normalize_legacy_output_entry('legacy_outputs', raw, created_at)]


def normalize_legacy_commands(raw: Any, created_at: str) -> list[dict[str, Any]]:
    if raw is None or raw == '':
        return []
    if isinstance(raw, list):
        entries: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                entries.append(item)
            elif item is not None and str(item).strip():
                entries.append({'command': str(item), 'cwd': '', 'exit_code': '', 'recorded_at': created_at, 'notes': 'migrated legacy command'})
        return entries
    if isinstance(raw, dict):
        return [{'command': '', 'cwd': '', 'exit_code': '', 'recorded_at': created_at, 'notes': 'migrated legacy command mapping', 'value': raw}]
    return [{'command': str(raw), 'cwd': '', 'exit_code': '', 'recorded_at': created_at, 'notes': 'migrated legacy command'}]


def normalize_legacy_string_list(raw: Any) -> list[str]:
    if raw is None or raw == '':
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if item is not None and str(item).strip()]
    return [str(raw)]


def normalize_run_manifest_for_branch(root: Path, manifest: dict[str, Any], rdir: Path, branch_id: str) -> dict[str, Any]:
    run_id = str(manifest.get('run_id') or rdir.name)
    manifest['run_id'] = run_id
    manifest['branch_id'] = str(manifest.get('branch_id') or branch_id)
    manifest['task_id'] = str(manifest.get('task_id') or infer_task_id_for_run_from_links(root, run_id, branch_id))
    manifest.setdefault('status', 'active')
    created_at = str(manifest.get('created_at') or manifest.get('start_time') or now_iso())
    manifest['created_at'] = created_at
    if 'closed_at' not in manifest:
        manifest['closed_at'] = manifest.get('end_time')
    if not isinstance(manifest.get('code_ref'), dict):
        manifest['code_ref'] = {}
    if not isinstance(manifest.get('environment'), dict):
        manifest['environment'] = environment_snapshot()
    manifest['inputs'] = normalize_legacy_inputs(manifest.get('inputs'), created_at)
    manifest['commands'] = normalize_legacy_commands(manifest.get('commands'), created_at)
    manifest['outputs'] = normalize_legacy_outputs(manifest.get('outputs'), created_at)
    manifest['promoted_to'] = normalize_legacy_string_list(manifest.get('promoted_to') if 'promoted_to' in manifest else manifest.get('promoted'))
    if not isinstance(manifest.get('parameters'), dict):
        old_parameters = manifest.get('parameters')
        manifest['parameters'] = {'legacy_parameters': old_parameters} if old_parameters not in (None, '') else {}
    if not isinstance(manifest.get('metrics'), dict):
        old_metrics = manifest.get('metrics')
        manifest['metrics'] = {'legacy_metrics': old_metrics} if old_metrics not in (None, '') else {}
    if not manifest.get('metrics') and isinstance(manifest.get('key_results'), dict):
        manifest['metrics'] = manifest['key_results']
    manifest.setdefault('result_status', 'draft')
    manifest.setdefault('notes', '')
    return manifest


def backfill_results_for_branch(root: Path, branch_id: str) -> None:
    path = indexes_dir(root) / 'results.tsv'
    if not path.exists():
        write_tsv(path, INDEX_HEADERS['results.tsv'], [])
        return
    run_by_id = {row.get('run_id', ''): row for row in read_tsv(indexes_dir(root) / 'runs.tsv') if row.get('run_id')}
    upgraded: list[dict[str, Any]] = []
    for row in read_tsv(path):
        item = {h: row.get(h, '') for h in INDEX_HEADERS['results.tsv']}
        item['branch_id'] = item.get('branch_id') or branch_id
        if not item.get('run_id'):
            item['run_id'] = infer_run_id_for_result_from_links(root, item.get('result_id', ''), item.get('branch_id') or branch_id) or infer_run_id_from_result_path(root, item.get('path', ''), item.get('branch_id') or branch_id)
        run_row = run_by_id.get(item.get('run_id', ''))
        if run_row:
            item['branch_id'] = run_row.get('branch_id', '') or item.get('branch_id') or branch_id
            item['task_id'] = item.get('task_id') or run_row.get('task_id', '')
        if not item.get('task_id') and item.get('result_id'):
            item['task_id'] = infer_task_id_for_result_from_links(root, item['result_id'], item.get('branch_id') or branch_id)
        item['promoted_to'] = item.get('promoted_to', '')
        item['replaced_by'] = item.get('replaced_by', '')
        upgraded.append(item)
    write_tsv(path, INDEX_HEADERS['results.tsv'], upgraded)


def rewrite_migrated_path(raw: str, path_map: list[tuple[str, str]]) -> str:
    if not raw:
        return raw
    normalized = raw.replace('\\', '/')
    for source, target in sorted(path_map, key=lambda item: len(item[0]), reverse=True):
        source = source.rstrip('/')
        target = target.rstrip('/')
        if normalized == source:
            return target
        if normalized.startswith(source + '/'):
            return target + normalized[len(source):]
    return raw


def rewrite_migration_links(root: Path, path_map: list[tuple[str, str]]) -> None:
    if not path_map:
        return
    results_path = indexes_dir(root) / 'results.tsv'
    if results_path.exists():
        rows = read_tsv(results_path)
        for row in rows:
            row['path'] = rewrite_migrated_path(row.get('path', ''), path_map)
            row['promoted_to'] = ','.join(rewrite_migrated_path(item, path_map) for item in row.get('promoted_to', '').split(',') if item)
        write_tsv(results_path, INDEX_HEADERS['results.tsv'], [{h: row.get(h, '') for h in INDEX_HEADERS['results.tsv']} for row in rows])
    assets_path = indexes_dir(root) / 'assets.tsv'
    if assets_path.exists():
        rows = read_tsv(assets_path)
        for row in rows:
            row['path'] = rewrite_migrated_path(row.get('path', ''), path_map)
        write_tsv(assets_path, INDEX_HEADERS['assets.tsv'], [{h: row.get(h, '') for h in INDEX_HEADERS['assets.tsv']} for row in rows])
    asset_locations_path = indexes_dir(root) / 'asset_locations.tsv'
    if asset_locations_path.exists():
        rows = read_tsv(asset_locations_path)
        for row in rows:
            row['path'] = rewrite_migrated_path(row.get('path', ''), path_map)
        write_tsv(asset_locations_path, INDEX_HEADERS['asset_locations.tsv'], [{h: row.get(h, '') for h in INDEX_HEADERS['asset_locations.tsv']} for row in rows])
    for tdir in list((project_os(root) / 'branches').glob('*/tasks/*')) + list((project_os(root) / 'tasks').glob('*')):
        if not tdir.is_dir():
            continue
        run_links = tdir / 'run_links.tsv'
        if run_links.exists():
            rows = read_tsv(run_links)
            for row in rows:
                row['path'] = rewrite_migrated_path(row.get('path', ''), path_map)
            write_tsv(run_links, RUN_LINK_HEADERS, [{h: row.get(h, '') for h in RUN_LINK_HEADERS} for row in rows])
        result_links = tdir / 'result_links.tsv'
        if result_links.exists():
            rows = read_tsv(result_links)
            for row in rows:
                row['path'] = rewrite_migrated_path(row.get('path', ''), path_map)
            write_tsv(result_links, RESULT_LINK_HEADERS, [{h: row.get(h, '') for h in RESULT_LINK_HEADERS} for row in rows])
    for run_root in [root / 'runs', root / 'analysis_runs']:
        if not run_root.exists():
            continue
        for manifest_path in sorted(run_root.glob('*/*/RUN_MANIFEST.json')):
            manifest = read_json(manifest_path)
            for entry in manifest.get('inputs', []) if isinstance(manifest.get('inputs'), list) else []:
                if isinstance(entry, dict) and entry.get('path'):
                    entry['path'] = rewrite_migrated_path(str(entry.get('path', '')), path_map)
            for entry in manifest.get('outputs', []) if isinstance(manifest.get('outputs'), list) else []:
                if isinstance(entry, dict) and entry.get('path'):
                    entry['path'] = rewrite_migrated_path(str(entry.get('path', '')), path_map)
            promoted = manifest.get('promoted_to', [])
            if isinstance(promoted, list):
                manifest['promoted_to'] = [rewrite_migrated_path(str(item), path_map) for item in promoted]
            write_json(manifest_path, manifest)


def looks_like_url(raw: str) -> bool:
    return bool(re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', raw or ''))


def migration_path_map(actions: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(a.get('source', ''), a.get('target', '')) for a in actions if a.get('kind') == 'run' and a.get('source') and a.get('target')]


def action_branch_id(action: dict[str, Any], default_branch_id: str) -> str:
    if action.get('kind') == 'branch':
        return str(action.get('id') or action.get('branch_id') or default_branch_id)
    return str(action.get('branch_id') or default_branch_id)


def valid_branch_id(raw: str) -> bool:
    return bool(re.match(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$', raw or ''))


def dedupe_migration_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for action in actions:
        key = (str(action.get('kind', '')), str(action.get('id', '')), str(action.get('target', '')))
        if key in seen:
            continue
        seen.add(key)
        out.append(action)
    return out


def scaffold_migration_plan(root: Path, branch_id: str, *, include_global: bool = True) -> list[dict[str, Any]]:
    """Plan non-destructive scaffold repairs needed by old flat harnesses.

    Early prototypes could have `.project_os/workflow.md`, runtime pointers, and
    flat `.project_os/tasks/` without the later branch-first anchors
    (`project.json`, `events.jsonl`, `.project_os/branches/<branch_id>/`, and
    full index headers).  `migrate-branch-first` should be the safe adoption
    entry for those projects instead of failing before it can report a plan.
    """
    actions: list[dict[str, Any]] = []
    global_scaffold_paths = [
        ('project.json', project_os(root) / 'project.json', 'file'),
        ('workflow.md', project_os(root) / 'workflow.md', 'file'),
        ('config.yaml', project_os(root) / 'config.yaml', 'file'),
        ('spec_dir', project_os(root) / 'spec', 'dir'),
        ('runtime_dir', project_os(root) / 'runtime', 'dir'),
        ('indexes_dir', project_os(root) / 'indexes', 'dir'),
        ('events.jsonl', events_path(root), 'file'),
        ('branches_dir', project_os(root) / 'branches', 'dir'),
        ('journals_dir', project_os(root) / 'journals', 'dir'),
        ('exports_dir', project_os(root) / 'exports', 'dir'),
        ('runtime_sessions_dir', project_os(root) / 'runtime' / 'sessions', 'dir'),
        ('current_session', project_os(root) / 'runtime' / 'current_session', 'file'),
        ('current_branch', project_os(root) / 'runtime' / 'current_branch', 'file'),
        ('current_task', project_os(root) / 'runtime' / 'current_task', 'file'),
        ('current_run', project_os(root) / 'runtime' / 'current_run', 'file'),
        ('current_project_dir', root / 'current' / 'project', 'dir'),
        ('release_dir', root / 'release', 'dir'),
    ]
    branch_scaffold_paths = [
        ('branch_dir', branch_dir(root, branch_id), 'dir'),
        ('branch_tasks_dir', branch_dir(root, branch_id) / 'tasks', 'dir'),
        ('branch_research_dir', branch_dir(root, branch_id) / 'research', 'dir'),
        ('branch_notes_dir', branch_dir(root, branch_id) / 'notes', 'dir'),
        ('branch_current_dir', branch_current_dir(root, branch_id), 'dir'),
        ('branch_run_dir', root / 'runs' / branch_id, 'dir'),
    ]
    scaffold_paths = (global_scaffold_paths if include_global else []) + branch_scaffold_paths
    for item_id, path, path_kind in scaffold_paths:
        if not path.exists():
            action: dict[str, Any] = {'kind': 'scaffold', 'id': item_id, 'target': relpath(root, path), 'status': 'would_create', 'path_kind': path_kind, 'branch_id': branch_id if item_id.startswith('branch_') or item_id in {'branch_dir', 'branch_tasks_dir', 'branch_research_dir', 'branch_notes_dir', 'branch_current_dir', 'branch_run_dir'} else ''}
            if item_id == 'current_branch':
                action['value'] = branch_id
            actions.append(action)
    if include_global:
        for name in SPEC_TEXTS:
            path = project_os(root) / 'spec' / name
            if not path.exists():
                actions.append({'kind': 'scaffold', 'id': f'spec:{name}', 'target': relpath(root, path), 'status': 'would_create', 'path_kind': 'file', 'branch_id': ''})
        for name in ROOT_DOC_DEFAULTS:
            path = root / name
            if not path.exists():
                actions.append({'kind': 'scaffold', 'id': f'root:{name}', 'target': relpath(root, path), 'status': 'would_create', 'path_kind': 'file', 'branch_id': ''})
    branch_text_defaults = {
        'branch_objective': (branch_dir(root, branch_id) / 'objective.md', f'# Objective\n\nAdopted {branch_id} branch.\n'),
        'branch_context': (branch_dir(root, branch_id) / 'context.md', '# Context\n\nMigrated branch-level context.\n'),
        'branch_handoff': (branch_dir(root, branch_id) / 'handoff.md', '# Handoff\n\nMigrated branch handoff.\n'),
        'branch_decisions': (branch_dir(root, branch_id) / 'decisions.md', '# Decisions\n\n'),
    }
    for item_id, (path, text) in branch_text_defaults.items():
        if not path.exists():
            actions.append({'kind': 'scaffold', 'id': item_id, 'target': relpath(root, path), 'status': 'would_create', 'path_kind': 'file', 'template': item_id, 'branch_id': branch_id})
    branch_json = branch_dir(root, branch_id) / 'branch.json'
    if not branch_json.exists():
        actions.append({'kind': 'branch', 'id': branch_id, 'branch_id': branch_id, 'target': relpath(root, branch_dir(root, branch_id)), 'status': 'would_create_branch'})
    else:
        try:
            branch = read_json(branch_json)
            missing = [field for field in BRANCH_REQUIRED_FIELDS if field not in branch]
            if missing:
                actions.append({'kind': 'branch', 'id': branch_id, 'branch_id': branch_id, 'target': relpath(root, branch_dir(root, branch_id)), 'status': 'would_repair_branch_manifest', 'manifest_repairs': ','.join(missing)})
        except ProjectOSError as exc:
            actions.append({'kind': 'branch', 'id': branch_id, 'branch_id': branch_id, 'target': relpath(root, branch_json), 'status': 'malformed_branch_manifest', 'manifest_repairs': 'malformed_branch_manifest', 'issue': str(exc)})
    return actions


def index_key_conflicts(root: Path, name: str, key: str, allowed_paths: dict[str, set[str]], path_field: str) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    path = indexes_dir(root) / name
    if not path.exists():
        return conflicts
    seen: dict[str, int] = {}
    for row in read_tsv(path):
        value = row.get(key, '')
        if not value:
            continue
        seen[value] = seen.get(value, 0) + 1
        allowed = allowed_paths.get(value, set())
        row_path = row.get(path_field, '')
        if allowed and row_path and row_path not in allowed:
            conflicts.append({'code': f'{key}_conflict', 'kind': name, 'id': value, 'path': relpath(root, path), 'existing_path': row_path, 'allowed_paths': sorted(allowed), 'blocking': True})
    for value, count in seen.items():
        if count > 1:
            conflicts.append({'code': f'duplicate_{key}', 'kind': name, 'id': value, 'path': relpath(root, path), 'count': count, 'blocking': True})
    return conflicts


def flat_run_path_needs_rewrite(root: Path, raw: str, branch_id: str, path_map: list[tuple[str, str]]) -> bool:
    if not raw or looks_like_url(raw):
        return False
    normalized = raw.replace('\\', '/')
    if rewrite_migrated_path(normalized, path_map) != raw:
        return False
    parts = Path(normalized).parts
    if len(parts) < 2 or parts[0] not in {'runs', 'analysis_runs'}:
        return False
    # Already branch-first: runs/<branch_id>/<run_id>/...
    if parts[1] == branch_id:
        return False
    # Flat run path with an existing manifest but no migration action/path-map.
    return (root / parts[0] / parts[1] / 'RUN_MANIFEST.json').exists()


def collect_path_warnings(root: Path, branch_id: str, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    path_map = migration_path_map(actions)
    run_action_ids = {str(action.get('id', '')) for action in actions if action.get('kind') == 'run' and action.get('id')}
    result_branch_by_run_id = {str(action.get('id', '')): action_branch_id(action, branch_id) for action in actions if action.get('kind') == 'run' and action.get('id')}
    results_path = indexes_dir(root) / 'results.tsv'
    if results_path.exists():
        for row in read_tsv(results_path):
            result_id = row.get('result_id', '')
            inferred_run_id = row.get('run_id', '') or infer_run_id_for_result_from_links(root, result_id, row.get('branch_id', '') or branch_id) or infer_run_id_from_result_path(root, row.get('path', ''), row.get('branch_id', '') or branch_id)
            result_branch_id = row.get('branch_id', '') or result_branch_by_run_id.get(inferred_run_id, '') or branch_id
            if not inferred_run_id:
                warnings.append({'code': 'unresolved_result_run', 'kind': 'result-row', 'id': result_id, 'path': row.get('path', ''), 'issue': 'result row lacks run_id and no run can be inferred from its path'})
            elif run_action_ids and inferred_run_id not in run_action_ids:
                warnings.append({'code': 'result_run_not_in_migration_plan', 'kind': 'result-row', 'id': result_id, 'run_id': inferred_run_id, 'path': row.get('path', ''), 'issue': 'result appears to reference a run not covered by this migration plan'})
            if not row.get('task_id') and result_id and not infer_task_id_for_result_from_links(root, result_id, result_branch_id):
                warnings.append({'code': 'unresolved_result_task', 'kind': 'result-row', 'id': result_id, 'path': row.get('path', ''), 'issue': 'result row lacks task_id and no task link can be inferred'})
            for field in ['path', 'promoted_to']:
                raw_items = [row.get(field, '')] if field == 'path' else [item for item in row.get(field, '').split(',') if item]
                for raw in raw_items:
                    if not raw:
                        continue
                    if flat_run_path_needs_rewrite(root, raw, result_branch_id, path_map):
                        warnings.append({'code': 'unmapped_flat_result_path', 'kind': 'result-row', 'id': row.get('result_id', ''), 'field': field, 'path': raw, 'issue': 'path looks like flat run output but no matching run migration action was found'})
                    target, _ = project_relative_or_absolute(root, raw)
                    if not looks_like_url(raw) and not target.exists():
                        warnings.append({'code': 'missing_result_path', 'kind': 'result-row', 'id': row.get('result_id', ''), 'field': field, 'path': raw, 'issue': 'path does not currently exist'})
    assets_path = indexes_dir(root) / 'assets.tsv'
    if assets_path.exists():
        for row in read_tsv(assets_path):
            raw = row.get('path', '')
            if not raw or looks_like_url(raw):
                continue
            if flat_run_path_needs_rewrite(root, raw, branch_id, path_map):
                warnings.append({'code': 'asset_path_will_not_rewrite', 'kind': 'asset-row', 'id': row.get('asset_id', ''), 'path': raw, 'issue': 'asset path is under a flat run not covered by migration actions'})
            target, _ = project_relative_or_absolute(root, raw)
            if not target.exists() and row.get('status') != 'unavailable':
                warnings.append({'code': 'missing_asset_path', 'kind': 'asset-row', 'id': row.get('asset_id', ''), 'path': raw, 'issue': 'asset path does not currently exist'})
    return warnings


def migration_diagnostics(root: Path, branch_id: str, actions: list[dict[str, Any]], *, replace: bool = False) -> dict[str, Any]:
    conflicts: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    task_allowed: dict[str, set[str]] = {}
    run_allowed: dict[str, set[str]] = {}
    planned_task_branch: dict[str, str] = {}
    for action in actions:
        if action.get('kind') != 'task':
            continue
        target_branch_id = action_branch_id(action, branch_id)
        for task_id in {str(action.get('id', '') or ''), str(action.get('manifest_task_id', '') or '')}:
            if task_id:
                planned_task_branch[task_id] = target_branch_id
    for action in actions:
        kind = action.get('kind', '')
        target_branch_id = action_branch_id(action, branch_id)
        if kind in {'branch', 'task', 'run'} and target_branch_id and not valid_branch_id(target_branch_id):
            conflicts.append({'code': 'invalid_branch_id', 'kind': kind, 'id': action.get('id', ''), 'branch_id': target_branch_id, 'blocking': True, 'resolution': 'repair legacy branch_id to match [A-Za-z0-9][A-Za-z0-9_.-]{0,127} before migration'})
        if kind in {'task', 'run'} and action.get('status') == 'exists':
            conflicts.append({'code': 'target_exists', 'kind': kind, 'id': action.get('id', ''), 'target': action.get('target', ''), 'blocking': not replace, 'resolution': 'use --replace only after reviewing target contents, or rename/move the existing target'})
        if kind == 'task' and 'malformed_task_manifest' in str(action.get('manifest_repairs', '')).split(','):
            conflicts.append({'code': 'malformed_task_manifest', 'kind': 'task', 'id': action.get('id', ''), 'source': action.get('source', ''), 'blocking': True, 'resolution': 'repair task.json before migration'})
        if kind == 'task' and action.get('manifest_task_id') and action.get('manifest_task_id') != action.get('id'):
            conflicts.append({'code': 'task_id_mismatch', 'kind': 'task', 'id': action.get('id', ''), 'manifest_task_id': action.get('manifest_task_id', ''), 'source': action.get('source', ''), 'blocking': True, 'resolution': 'make task.json task_id match its directory name, or rename the task directory before migration'})
        if kind == 'task' and action.get('manifest_branch_id') and action.get('manifest_branch_id') != target_branch_id:
            conflicts.append({'code': 'task_branch_mismatch', 'kind': 'task', 'id': action.get('id', ''), 'manifest_branch_id': action.get('manifest_branch_id', ''), 'target_branch_id': target_branch_id, 'source': action.get('source', ''), 'blocking': True, 'resolution': 'rerun migration with the matching --branch-id, use --preserve-manifest-branches, or repair task.json branch_id before migration'})
        if kind == 'run' and 'malformed_manifest' in str(action.get('manifest_repairs', '')).split(','):
            conflicts.append({'code': 'malformed_run_manifest', 'kind': 'run', 'id': action.get('id', ''), 'source': action.get('source', ''), 'blocking': True, 'resolution': 'repair RUN_MANIFEST.json before migration'})
        if kind == 'run' and action.get('manifest_run_id') and action.get('manifest_run_id') != action.get('id'):
            conflicts.append({'code': 'run_id_mismatch', 'kind': 'run', 'id': action.get('id', ''), 'manifest_run_id': action.get('manifest_run_id', ''), 'source': action.get('source', ''), 'blocking': True, 'resolution': 'make RUN_MANIFEST.json run_id match its directory name, or rename the run directory before migration'})
        if kind == 'run' and action.get('manifest_branch_id') and action.get('manifest_branch_id') != target_branch_id:
            conflicts.append({'code': 'run_branch_mismatch', 'kind': 'run', 'id': action.get('id', ''), 'manifest_branch_id': action.get('manifest_branch_id', ''), 'target_branch_id': target_branch_id, 'source': action.get('source', ''), 'blocking': True, 'resolution': 'rerun migration with the matching --branch-id, use --preserve-manifest-branches, or repair RUN_MANIFEST.json branch_id before migration'})
        if kind == 'run' and action.get('manifest_task_id') and planned_task_branch.get(str(action.get('manifest_task_id'))) and planned_task_branch[str(action.get('manifest_task_id'))] != target_branch_id:
            conflicts.append({'code': 'run_task_branch_mismatch', 'kind': 'run', 'id': action.get('id', ''), 'manifest_task_id': action.get('manifest_task_id', ''), 'run_branch_id': target_branch_id, 'task_branch_id': planned_task_branch[str(action.get('manifest_task_id'))], 'source': action.get('source', ''), 'blocking': True, 'resolution': 'repair RUN_MANIFEST.json branch_id or task.json branch_id so the run and its task belong to the same branch before migration'})
        if kind == 'run' and action.get('manifest_task_id') and not task_json_path_for_migration(root, str(action.get('manifest_task_id')), target_branch_id):
            warnings.append({'code': 'run_task_not_found', 'kind': 'run', 'id': action.get('id', ''), 'manifest_task_id': action.get('manifest_task_id', ''), 'source': action.get('source', ''), 'issue': 'run manifest task_id is not present in flat or branch task workspaces'})
        if kind == 'branch' and 'malformed_branch_manifest' in str(action.get('manifest_repairs', '')).split(','):
            conflicts.append({'code': 'malformed_branch_manifest', 'kind': 'branch', 'id': action.get('id', ''), 'target': action.get('target', ''), 'blocking': True, 'resolution': 'repair branch.json before migration'})
        if kind == 'task':
            task_allowed.setdefault(action.get('id', ''), set()).update({action.get('source', ''), action.get('target', '')})
        elif kind == 'run':
            run_allowed.setdefault(action.get('id', ''), set()).update({action.get('source', ''), action.get('target', '')})
    conflicts.extend(index_key_conflicts(root, 'tasks.tsv', 'task_id', task_allowed, 'task_path'))
    conflicts.extend(index_key_conflicts(root, 'runs.tsv', 'run_id', run_allowed, 'run_path'))
    conflicts.extend(index_key_conflicts(root, 'results.tsv', 'result_id', {}, 'path'))
    warnings.extend(collect_path_warnings(root, branch_id, actions))
    summary = {
        'actions': len(actions),
        'scaffold_repairs': sum(1 for a in actions if a.get('kind') == 'scaffold'),
        'branch_repairs': sum(1 for a in actions if a.get('kind') == 'branch'),
        'tasks': sum(1 for a in actions if a.get('kind') == 'task'),
        'runs': sum(1 for a in actions if a.get('kind') == 'run'),
        'index_repairs': sum(1 for a in actions if a.get('kind') == 'index'),
        'result_row_repairs': sum(1 for a in actions if a.get('kind') == 'result-row'),
        'manifest_conflicts': sum(1 for c in conflicts if str(c.get('code', '')).endswith('_mismatch') or str(c.get('code', '')).startswith('malformed_')),
        'blocking_conflicts': sum(1 for c in conflicts if c.get('blocking')),
        'warnings': len(warnings),
    }
    return {'summary': summary, 'conflicts': conflicts, 'warnings': warnings, 'safe_to_apply': summary['blocking_conflicts'] == 0}


def task_json_path_for_migration(root: Path, task_id: str, branch_id: str) -> Path | None:
    candidates = [
        branch_task_dir(root, branch_id, task_id) / 'task.json',
        project_os(root) / 'tasks' / task_id / 'task.json',
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for task_file in sorted((project_os(root) / 'branches').glob('*/tasks/*/task.json')):
        try:
            data = read_json(task_file)
        except ProjectOSError:
            continue
        if str(data.get('task_id') or task_file.parent.name) == task_id:
            return task_file
    return None


def migration_target_branch(default_branch_id: str, manifest_branch_id: str, *, preserve_manifest_branches: bool = False) -> str:
    return str(manifest_branch_id or default_branch_id) if preserve_manifest_branches and manifest_branch_id else default_branch_id


def path_safe_branch_id(target_branch_id: str, default_branch_id: str) -> str:
    return target_branch_id if valid_branch_id(target_branch_id) else default_branch_id


def flat_migration_plan(root: Path, branch_id: str, *, preserve_manifest_branches: bool = False) -> list[dict[str, Any]]:
    object_actions: list[dict[str, Any]] = []
    migration_branch_ids: set[str] = {branch_id}
    task_branch_by_id: dict[str, str] = {}
    legacy_tasks = project_os(root) / 'tasks'
    if legacy_tasks.exists():
        for task_file in sorted(legacy_tasks.glob('*/task.json')):
            task_id = task_file.parent.name
            link_repairs = []
            manifest_repairs = []
            manifest_task_id = ''
            manifest_branch_id = ''
            try:
                task_manifest = read_json(task_file)
                manifest_task_id = str(task_manifest.get('task_id') or '')
                manifest_branch_id = str(task_manifest.get('branch_id') or '')
            except ProjectOSError:
                manifest_repairs.append('malformed_task_manifest')
            target_branch_id = migration_target_branch(branch_id, manifest_branch_id, preserve_manifest_branches=preserve_manifest_branches)
            safe_branch_id = path_safe_branch_id(target_branch_id, branch_id)
            if valid_branch_id(target_branch_id):
                migration_branch_ids.add(target_branch_id)
            task_branch_by_id[task_id] = target_branch_id
            if manifest_task_id:
                task_branch_by_id[manifest_task_id] = target_branch_id
            dest = branch_task_dir(root, safe_branch_id, task_id)
            if (task_file.parent / 'run_links.tsv').exists() and tsv_header(task_file.parent / 'run_links.tsv') != RUN_LINK_HEADERS:
                link_repairs.append('run_links.tsv')
            if (task_file.parent / 'result_links.tsv').exists() and tsv_header(task_file.parent / 'result_links.tsv') != RESULT_LINK_HEADERS:
                link_repairs.append('result_links.tsv')
            object_actions.append({
                'kind': 'task',
                'id': task_id,
                'branch_id': target_branch_id,
                'source': relpath(root, task_file.parent),
                'target': relpath(root, dest),
                'status': 'exists' if dest.exists() else 'would_move',
                'manifest_task_id': manifest_task_id,
                'manifest_branch_id': manifest_branch_id,
                'manifest_repairs': ','.join(manifest_repairs),
                'link_repairs': ','.join(link_repairs),
                'conflict': 'target_exists' if dest.exists() else '',
            })
    for runs_root in [root / 'runs', root / 'analysis_runs']:
        if runs_root.exists():
            for manifest_file in sorted(runs_root.glob('*/RUN_MANIFEST.json')):
                run_id = manifest_file.parent.name
                missing_fields = []
                manifest_run_id = ''
                manifest_branch_id = ''
                manifest_task_id = ''
                try:
                    manifest = read_json(manifest_file)
                    manifest_run_id = str(manifest.get('run_id') or '')
                    manifest_branch_id = str(manifest.get('branch_id') or '')
                    manifest_task_id = str(manifest.get('task_id') or '')
                    required = ['run_id', 'branch_id', 'task_id', 'status', 'created_at', 'closed_at', 'code_ref', 'environment', 'inputs', 'parameters', 'commands', 'outputs', 'metrics', 'result_status']
                    missing_fields = []
                    for field in required:
                        if field == 'created_at' and manifest.get('start_time'):
                            continue
                        if field == 'closed_at' and manifest.get('end_time'):
                            continue
                        if field not in manifest:
                            missing_fields.append(field)
                    if 'created_at' not in manifest and manifest.get('start_time'):
                        missing_fields.append('created_at_from_start_time')
                    if 'closed_at' not in manifest and manifest.get('end_time'):
                        missing_fields.append('closed_at_from_end_time')
                    if 'promoted_to' not in manifest and 'promoted' in manifest:
                        missing_fields.append('promoted_to_from_promoted')
                    for list_field in ['inputs', 'commands', 'outputs', 'promoted_to']:
                        if list_field in manifest and not isinstance(manifest.get(list_field), list):
                            missing_fields.append(f'normalize_{list_field}_shape')
                    if isinstance(manifest.get('inputs'), list) and any(not isinstance(item, dict) for item in manifest.get('inputs', [])):
                        missing_fields.append('normalize_inputs_entries')
                    if isinstance(manifest.get('commands'), list) and any(not isinstance(item, dict) for item in manifest.get('commands', [])):
                        missing_fields.append('normalize_commands_entries')
                    if isinstance(manifest.get('outputs'), list) and any(not isinstance(item, dict) for item in manifest.get('outputs', [])):
                        missing_fields.append('normalize_outputs_entries')
                    if not isinstance(manifest.get('parameters', {}), dict):
                        missing_fields.append('wrap_legacy_parameters')
                    if not isinstance(manifest.get('metrics', {}), dict):
                        missing_fields.append('wrap_legacy_metrics')
                    if 'metrics' not in manifest and isinstance(manifest.get('key_results'), dict):
                        missing_fields.append('metrics_from_key_results')
                except ProjectOSError:
                    missing_fields = ['malformed_manifest']
                task_branch_id = task_branch_by_id.get(manifest_task_id, '')
                target_branch_id = migration_target_branch(branch_id, manifest_branch_id or task_branch_id, preserve_manifest_branches=preserve_manifest_branches)
                safe_branch_id = path_safe_branch_id(target_branch_id, branch_id)
                if valid_branch_id(target_branch_id):
                    migration_branch_ids.add(target_branch_id)
                dest = run_dir(root, safe_branch_id, run_id, runs_root.name)
                object_actions.append({
                    'kind': 'run',
                    'id': run_id,
                    'branch_id': target_branch_id,
                    'source': relpath(root, manifest_file.parent),
                    'target': relpath(root, dest),
                    'status': 'exists' if dest.exists() else 'would_move',
                    'run_root': runs_root.name,
                    'manifest_run_id': manifest_run_id,
                    'manifest_branch_id': manifest_branch_id,
                    'manifest_task_id': manifest_task_id,
                    'manifest_repairs': ','.join(missing_fields),
                    'conflict': 'target_exists' if dest.exists() else '',
                })
    branch_order = [branch_id] + sorted(bid for bid in migration_branch_ids if bid != branch_id)
    actions: list[dict[str, Any]] = []
    for bid in branch_order:
        actions.extend(scaffold_migration_plan(root, bid, include_global=(bid == branch_id)))
    actions = dedupe_migration_actions(actions)
    actions.extend(object_actions)
    for name in INDEX_HEADERS:
        path = indexes_dir(root) / name
        if not path.exists():
            actions.append({'kind': 'index', 'id': name, 'source': '', 'target': relpath(root, path), 'status': 'would_create_index'})
            continue
        actual = tsv_header(path)
        if actual != INDEX_HEADERS[name]:
            actions.append({'kind': 'index', 'id': name, 'source': relpath(root, path), 'target': relpath(root, path), 'status': 'would_upgrade_header'})
    results_path = indexes_dir(root) / 'results.tsv'
    if results_path.exists():
        for row in read_tsv(results_path):
            if not row.get('branch_id') or not row.get('task_id') or not row.get('run_id') or 'promoted_to' not in row:
                actions.append({'kind': 'result-row', 'id': row.get('result_id', ''), 'source': relpath(root, results_path), 'target': relpath(root, results_path), 'status': 'would_patch_branch_fields'})
    return actions


def upgrade_index_rows_for_branch(root: Path, name: str, branch_id: str) -> None:
    path = indexes_dir(root) / name
    if not path.exists():
        write_tsv(path, INDEX_HEADERS[name], [])
        return
    rows = read_tsv(path)
    upgraded: list[dict[str, Any]] = []
    for row in rows:
        item = {h: row.get(h, '') for h in INDEX_HEADERS[name]}
        if name in {'tasks.tsv', 'runs.tsv', 'results.tsv'} and not item.get('branch_id'):
            item['branch_id'] = branch_id
        if name == 'results.tsv':
            item.setdefault('promoted_to', '')
            item.setdefault('replaced_by', '')
        upgraded.append(item)
    write_tsv(path, INDEX_HEADERS[name], upgraded)


def apply_scaffold_action(root: Path, action: dict[str, Any]) -> None:
    target = root / str(action.get('target', ''))
    if action.get('id') == 'project.json':
        if not target.exists():
            write_json(target, project_json_payload(root, 'research'))
        return
    if action.get('id') == 'workflow.md':
        write_missing_text_if_absent(target, WORKFLOW_TEXT)
        return
    if action.get('id') == 'config.yaml':
        write_missing_text_if_absent(target, CONFIG_TEXT)
        return
    if action.get('id') == 'events.jsonl':
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text('', encoding='utf-8')
        return
    if str(action.get('id', '')).startswith('spec:'):
        name = str(action.get('id', '')).split(':', 1)[1]
        write_missing_text_if_absent(target, SPEC_TEXTS.get(name, f'# {name}\n'))
        return
    if str(action.get('id', '')).startswith('root:'):
        name = str(action.get('id', '')).split(':', 1)[1]
        write_missing_text_if_absent(target, ROOT_DOC_DEFAULTS.get(name, f'# {name}\n'))
        return
    if action.get('id') == 'current_branch':
        write_missing_text_if_absent(target, str(action.get('value') or DEFAULT_BRANCH).strip() + '\n')
        return
    if action.get('id') in {'current_task', 'current_run', 'current_session'}:
        write_missing_text_if_absent(target, '')
        return
    if action.get('id') == 'branch_objective':
        write_missing_text_if_absent(target, f"# Objective\n\nAdopted branch.\n")
        return
    if action.get('id') == 'branch_context':
        write_missing_text_if_absent(target, '# Context\n\nMigrated branch-level context.\n')
        return
    if action.get('id') == 'branch_handoff':
        write_missing_text_if_absent(target, '# Handoff\n\nMigrated branch handoff.\n')
        return
    if action.get('id') == 'branch_decisions':
        write_missing_text_if_absent(target, '# Decisions\n\n')
        return
    if action.get('path_kind') == 'dir':
        target.mkdir(parents=True, exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text('', encoding='utf-8')


def command_migrate_branch_first(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not project_os(root).exists():
        raise ProjectOSError(f'Missing {OS_DIR}. Run init/new-project first, or create a legacy .project_os before migration.')
    branch_id = args.branch_id or DEFAULT_BRANCH
    actions = flat_migration_plan(root, branch_id, preserve_manifest_branches=bool(getattr(args, 'preserve_manifest_branches', False)))
    diagnostics = migration_diagnostics(root, branch_id, actions, replace=bool(args.replace))
    if not args.apply:
        planned_branches = sorted({action_branch_id(action, branch_id) for action in actions if action.get('kind') in {'branch', 'task', 'run'} and action_branch_id(action, branch_id)})
        print_json({'dry_run_migration': {
            'branch_id': branch_id,
            'preserve_manifest_branches': bool(getattr(args, 'preserve_manifest_branches', False)),
            'planned_branches': planned_branches,
            'actions': actions,
            'diagnostics': diagnostics,
            'summary': diagnostics.get('summary', {}),
            'conflicts': diagnostics.get('conflicts', []),
            'warnings': diagnostics.get('warnings', []),
            'safe_to_apply': diagnostics.get('safe_to_apply', False),
            'apply_required': True,
            'mode': args.mode,
        }}); return 0
    blocking = [item for item in diagnostics['conflicts'] if item.get('blocking')]
    if blocking:
        raise ProjectOSError(f'Migration has blocking conflicts; run dry-run and resolve first: {blocking[0].get("code")} {blocking[0].get("id", "")}')
    applied: list[dict[str, str]] = []
    path_map: list[tuple[str, str]] = []
    for action in actions:
        target_branch_id = action_branch_id(action, branch_id)
        if action['kind'] == 'scaffold':
            apply_scaffold_action(root, action)
            new_action = dict(action); new_action['status'] = 'created' if action.get('status') == 'would_create' else action.get('status', 'applied'); applied.append(new_action)
            continue
        if action['kind'] == 'branch':
            branch_for_action = target_branch_id
            title = f'Adopted {branch_for_action} branch'
            notes = 'Created by migrate-branch-first while adopting an older flat harness.'
            parent_branch_id = ''
            git_branch = ''
            bj = branch_dir(root, branch_for_action) / 'branch.json'
            if bj.exists():
                old = read_json(bj)
                title = str(old.get('title') or title)
                notes = str(old.get('notes') or notes)
                parent_branch_id = str(old.get('parent_branch_id') or '')
                git_branch = str(old.get('git_branch') or '')
            create_branch_record(root, branch_for_action, title, parent_branch_id=parent_branch_id, git_branch=git_branch, notes=notes, set_current=(current_pointer(root, 'current_branch') in {'', branch_for_action}), allow_existing=True)
            new_action = dict(action); new_action['status'] = 'created_branch'; applied.append(new_action)
            continue
        if action['kind'] == 'index':
            upgrade_index_rows_for_branch(root, action['id'], branch_id)
            new_action = dict(action); new_action['status'] = 'created_index' if action.get('status') == 'would_create_index' else 'upgraded_header'; applied.append(new_action)
            continue
        if action['kind'] == 'result-row':
            upgrade_index_rows_for_branch(root, 'results.tsv', branch_id)
            new_action = dict(action); new_action['status'] = 'patched_branch_fields'; applied.append(new_action)
            continue
        if action['status'] == 'exists' and not args.replace:
            raise ProjectOSError(f'Migration target exists; pass --replace or handle manually: {action["target"]}')
        source = root / action['source']; target = root / action['target']
        if action['status'] == 'exists' and args.replace:
            if target.is_dir(): shutil.rmtree(target)
            elif target.exists(): target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        if args.mode == 'copy':
            shutil.copytree(source, target)
        else:
            shutil.move(source.as_posix(), target.as_posix())
        if action['kind'] == 'task':
            tjson = target / 'task.json'
            task = read_json(tjson)
            task['task_id'] = str(task.get('task_id') or action['id'])
            task.setdefault('title', action['id'])
            task.setdefault('status', 'active')
            task.setdefault('kind', 'analysis')
            task.setdefault('stage', 'Intake')
            task.setdefault('created_at', now_iso())
            task['branch_id'] = target_branch_id
            task['task_path'] = relpath(root, target)
            task['updated_at'] = now_iso()
            task.setdefault('objective_file', 'objective.md')
            task.setdefault('context_file', 'context.md')
            task.setdefault('context_manifest', 'context_manifest.jsonl')
            task.setdefault('handoff_file', 'handoff.md')
            task.setdefault('depends_on', {'tasks': [], 'results': []})
            write_json(tjson, task)
            write_missing_text_if_absent(target / str(task.get('objective_file', 'objective.md')), f"# Objective\n\n{task.get('title', action['id'])}\n")
            write_missing_text_if_absent(target / str(task.get('context_file', 'context.md')), '# Context\n\nMigrated task context.\n')
            write_missing_text_if_absent(target / str(task.get('context_manifest', 'context_manifest.jsonl')), default_context_manifest())
            write_missing_text_if_absent(target / str(task.get('handoff_file', 'handoff.md')), '# Handoff\n\nMigrated task handoff.\n')
            write_missing_text_if_absent(target / 'decisions.md', '# Decisions\n\n')
            normalize_task_link_tables(root, target, target_branch_id)
        elif action['kind'] == 'run':
            manifest_path = target / 'RUN_MANIFEST.json'
            manifest = normalize_run_manifest_for_branch(root, read_json(manifest_path), target, target_branch_id)
            write_json(manifest_path, manifest)
            path_map.append((action['source'], action['target']))
        new_action = dict(action); new_action['status'] = 'copied' if args.mode == 'copy' else 'moved'; applied.append(new_action)
    rewrite_migration_links(root, path_map)
    applied_branch_ids = sorted({action_branch_id(action, branch_id) for action in applied if action.get('kind') in {'branch', 'task', 'run'} and action_branch_id(action, branch_id)} or {branch_id})
    for bid in applied_branch_ids:
        if not branch_row(root, bid):
            create_branch_record(root, bid, f'Adopted {bid} branch', notes='Created by migrate-branch-first while adopting an older flat harness.', set_current=(current_pointer(root, 'current_branch') in {'', bid}), allow_existing=True)
    refresh_branch_index(root); refresh_task_index(root); refresh_run_index(root)
    for bid in applied_branch_ids:
        backfill_results_for_branch(root, bid)
    refresh_asset_usage(root); refresh_results_index_markdown(root); refresh_data_assets_markdown(root)
    append_event(root, 'project.adopted', branch_id=branch_id, detail={'command': 'migrate-branch-first', 'mode': args.mode, 'actions': len(applied), 'branches': applied_branch_ids, 'preserve_manifest_branches': bool(getattr(args, 'preserve_manifest_branches', False))})
    print_json({'migrated_branch_first': {
        'branch_id': branch_id,
        'branches': applied_branch_ids,
        'preserve_manifest_branches': bool(getattr(args, 'preserve_manifest_branches', False)),
        'mode': args.mode,
        'actions': applied,
        'diagnostics': diagnostics,
        'summary': diagnostics.get('summary', {}),
        'conflicts': diagnostics.get('conflicts', []),
        'warnings': diagnostics.get('warnings', []),
        'safe_to_apply': diagnostics.get('safe_to_apply', False),
    }}); return 0
