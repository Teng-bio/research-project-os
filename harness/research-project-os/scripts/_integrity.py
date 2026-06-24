from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from _schema import *
from _paths import *
from _project_io import *
from _views import data_assets_view_status, promotion_audit, results_index_markdown_text


def validate_headers(path: Path, expected: list[str], errors: list[dict[str, str]]) -> None:
    if not path.exists(): errors.append({'path': path.as_posix(), 'issue': 'missing index'}); return
    first = path.read_text(encoding='utf-8', errors='replace').splitlines()[:1]
    actual = first[0].split('\t') if first else []
    if actual != expected: errors.append({'path': path.as_posix(), 'issue': f'header mismatch: expected {expected}, got {actual}'})


def validate_unique_tsv_key(path: Path, key: str, errors: list[dict[str, str]]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in read_tsv(path):
        value = row.get(key, '')
        if not value:
            continue
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    for value in sorted(duplicates):
        errors.append({'path': path.as_posix(), 'issue': f'duplicate {key}: {value}'})


def validate_context_manifest(root: Path, path: Path, errors: list[dict[str, str]], warnings: list[dict[str, str]]) -> None:
    if not path.exists(): errors.append({'path': path.as_posix(), 'issue': 'missing context manifest'}); return
    for idx, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        if not line.strip(): continue
        try: item = json.loads(line)
        except json.JSONDecodeError as exc: errors.append({'path': path.as_posix(), 'issue': f'line {idx}: malformed JSONL: {exc}'}); continue
        for key in ['type', 'path', 'purpose', 'required']:
            if key not in item: errors.append({'path': path.as_posix(), 'issue': f'line {idx}: missing key {key}'})
        item_path = str(item.get('path', '')); required = bool(item.get('required', False))
        target = (root / item_path) if item_path and not Path(item_path).is_absolute() else (Path(item_path) if item_path else None)
        if required and target and not target.exists(): errors.append({'path': path.as_posix(), 'issue': f'line {idx}: required context path missing: {item_path}'})
        elif target and item_path and not target.exists(): warnings.append({'path': path.as_posix(), 'issue': f'line {idx}: optional context path missing: {item_path}'})


def normalized_text(path: Path) -> str:
    return path.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n') if path.exists() else ''


def parse_event_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return parsed
    except ValueError:
        return None


def latest_legacy_adoption_time(events: list[dict[str, Any]]) -> datetime | None:
    times = [parse_event_time(str(event.get('ts', ''))) for event in events if event.get('event') == 'project.adopted']
    valid = [item for item in times if item is not None]
    return max(valid) if valid else None


def row_time(row: dict[str, str], *fields: str) -> datetime | None:
    for field in fields:
        parsed = parse_event_time(str(row.get(field, '')))
        if parsed is not None:
            return parsed
    return None


def is_legacy_adopted(row: dict[str, str], adopted_at: datetime | None, *fields: str) -> bool:
    if adopted_at is None:
        return False
    created = row_time(row, *fields)
    # If an adopted row lacks a reliable timestamp, avoid inventing a hard failure.
    return created is None or created <= adopted_at


def add_journal_snapshot_checks(
    root: Path,
    branch_rows: list[dict[str, str]],
    task_rows: list[dict[str, str]],
    run_rows: list[dict[str, str]],
    result_rows: list[dict[str, str]],
    asset_rows: list[dict[str, str]],
    release_rows: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    path = events_path(root)
    if not path.exists():
        return
    events = [event for event in read_jsonl(path) if not event.get('_error')]
    if not events:
        return
    adopted_at = latest_legacy_adoption_time(events)
    refs: dict[str, set[str]] = {
        'branch': set(),
        'task': set(),
        'run': set(),
        'result': set(),
        'asset': set(),
        'release': set(),
    }
    for event in events:
        detail = event.get('detail', {}) if isinstance(event.get('detail'), dict) else {}
        for kind, field in [('branch', 'branch_id'), ('task', 'task_id'), ('run', 'run_id'), ('result', 'result_id')]:
            value = str(event.get(field, '') or '')
            if value:
                refs[kind].add(value)
            detail_value = str(detail.get(field, '') or '')
            if detail_value:
                refs[kind].add(detail_value)
        for asset_id in [str(detail.get('asset_id', '') or '')]:
            if asset_id:
                refs['asset'].add(asset_id)
        for release_id in [str(detail.get('release_id', '') or '')]:
            if release_id:
                refs['release'].add(release_id)
        for result_id in [item.strip() for item in str(detail.get('result_ids', '') or '').split(',') if item.strip()]:
            refs['result'].add(result_id)

    checks = [
        ('branch', branch_rows, 'branch_id', ('created_at',)),
        ('task', task_rows, 'task_id', ('created_at', 'updated_at')),
        ('run', run_rows, 'run_id', ('created_at', 'closed_at')),
        ('result', result_rows, 'result_id', ('created_at', 'accepted_at')),
        ('asset', asset_rows, 'asset_id', ('registered_at',)),
        ('release', release_rows, 'release_id', ('created_at',)),
    ]
    for kind, rows, id_field, time_fields in checks:
        for row in rows:
            object_id = row.get(id_field, '')
            if not object_id or object_id in refs[kind]:
                continue
            if is_legacy_adopted(row, adopted_at, *time_fields):
                continue
            warnings.append({'path': path.as_posix(), 'issue': f'journal snapshot missing event coverage: {kind} {object_id}'})


def add_integrity_checks(root: Path, errors: list[dict[str, str]], warnings: list[dict[str, str]]) -> None:
    os_dir = project_os(root)
    idx = indexes_dir(root)
    branch_rows = read_tsv(idx / 'branches.tsv') if (idx / 'branches.tsv').exists() else []
    task_rows = read_tsv(idx / 'tasks.tsv') if (idx / 'tasks.tsv').exists() else []
    run_rows = read_tsv(idx / 'runs.tsv') if (idx / 'runs.tsv').exists() else []
    result_rows = read_tsv(idx / 'results.tsv') if (idx / 'results.tsv').exists() else []
    asset_rows = read_tsv(idx / 'assets.tsv') if (idx / 'assets.tsv').exists() else []
    asset_location_rows = read_tsv(idx / 'asset_locations.tsv') if (idx / 'asset_locations.tsv').exists() else []
    release_rows = read_tsv(idx / 'releases.tsv') if (idx / 'releases.tsv').exists() else []
    task_by_id = {row.get('task_id', ''): row for row in task_rows if row.get('task_id')}
    branch_by_id = {row.get('branch_id', ''): row for row in branch_rows if row.get('branch_id')}
    result_by_id = {row.get('result_id', ''): row for row in result_rows if row.get('result_id')}

    current_b = current_pointer(root, 'current_branch') if (os_dir / 'runtime').exists() else ''
    if current_b and branch_by_id.get(current_b, {}).get('status') in {'archived', 'abandoned'}:
        errors.append({'path': (os_dir / 'runtime' / 'current_branch').as_posix(), 'issue': f'current_branch points to inactive branch: {current_b}'})

    inactive_branch_ids = {row.get('branch_id', '') for row in branch_rows if row.get('status') in {'archived', 'abandoned'}}
    for branch_id in sorted(inactive_branch_ids):
        active_tasks = [row.get('task_id', '') for row in task_rows if row.get('branch_id') == branch_id and row.get('status') in {'active', 'paused', 'blocked'}]
        active_runs = [row.get('run_id', '') for row in run_rows if row.get('branch_id') == branch_id and row.get('status') in {'active', 'pending_review'}]
        if active_tasks:
            warnings.append({'path': (idx / 'tasks.tsv').as_posix(), 'issue': f'inactive branch has active tasks: {branch_id} -> {",".join(active_tasks)}'})
        if active_runs:
            warnings.append({'path': (idx / 'runs.tsv').as_posix(), 'issue': f'inactive branch has active runs: {branch_id} -> {",".join(active_runs)}'})

    # Result replacement graph: no self edges, no missing nodes, no cycles.
    graph = {row.get('result_id', ''): row.get('replaced_by', '') for row in result_rows if row.get('result_id') and row.get('replaced_by')}
    for result_id, replaced_by in graph.items():
        if result_id == replaced_by:
            errors.append({'path': (idx / 'results.tsv').as_posix(), 'issue': f'result replaces itself: {result_id}'})
        elif replaced_by not in result_by_id:
            warnings.append({'path': (idx / 'results.tsv').as_posix(), 'issue': f'result replaced_by missing: {result_id} -> {replaced_by}'})
    for start in sorted(graph):
        seen: set[str] = set()
        node = start
        while graph.get(node):
            node = graph[node]
            if node in seen:
                errors.append({'path': (idx / 'results.tsv').as_posix(), 'issue': f'result replaced_by cycle includes: {start}'})
                break
            seen.add(node)

    for row in result_rows:
        result_id = row.get('result_id', '')
        task = task_by_id.get(row.get('task_id', ''))
        if task and task.get('status') in {'superseded', 'archived'} and row.get('status') == 'current':
            warnings.append({'path': (idx / 'results.tsv').as_posix(), 'issue': f'current result belongs to inactive task: {result_id} task={task.get("task_id")}'})
        for target in [item for item in row.get('promoted_to', '').split(',') if item]:
            match = re.match(r'^current/branches/([^/]+)/', target)
            if match and match.group(1) != row.get('branch_id'):
                warnings.append({'path': (idx / 'results.tsv').as_posix(), 'issue': f'cross-branch promotion target: {result_id} branch={row.get("branch_id")} target={target}'})

    audit = promotion_audit(root, result_rows)
    for item in audit.get('missing_current_targets', []):
        warnings.append({'path': (idx / 'results.tsv').as_posix(), 'issue': f'missing current target: {item.get("result_id")} -> {item.get("target")}'})
    for item in audit.get('duplicate_current_targets', []):
        warnings.append({'path': (idx / 'results.tsv').as_posix(), 'issue': f'duplicate current target: {item.get("target")} <- {",".join(item.get("result_ids", []))}'})
    for item in audit.get('unscoped_current_results', []):
        warnings.append({'path': (idx / 'results.tsv').as_posix(), 'issue': f'unscoped current result has no promoted_to target: {item.get("result_id")} branch={item.get("branch_id")}'})

    task_dep_graph: dict[str, list[str]] = {}
    for task_file in sorted((os_dir / 'branches').glob('*/tasks/*/task.json')):
        try:
            task = read_json(task_file)
        except ProjectOSError as exc:
            errors.append({'path': task_file.as_posix(), 'issue': str(exc)})
            continue
        task_id = str(task.get('task_id') or task_file.parent.name)
        depends_on = task.get('depends_on', {})
        if depends_on in ('', None):
            depends_on = {'tasks': [], 'results': []}
        if not isinstance(depends_on, dict):
            errors.append({'path': task_file.as_posix(), 'issue': 'depends_on must be an object with tasks/results arrays'})
            continue
        dep_tasks = depends_on.get('tasks', [])
        dep_results = depends_on.get('results', [])
        if not isinstance(dep_tasks, list) or not isinstance(dep_results, list):
            errors.append({'path': task_file.as_posix(), 'issue': 'depends_on.tasks and depends_on.results must be arrays'})
            continue
        task_dep_graph[task_id] = [str(dep) for dep in dep_tasks]
        for dep in dep_tasks:
            dep = str(dep)
            if dep == task_id:
                errors.append({'path': task_file.as_posix(), 'issue': f'task depends on itself: {task_id}'})
            elif dep not in task_by_id:
                warnings.append({'path': task_file.as_posix(), 'issue': f'task dependency missing: {task_id} -> {dep}'})
        for dep in dep_results:
            dep = str(dep)
            if dep not in result_by_id:
                warnings.append({'path': task_file.as_posix(), 'issue': f'result dependency missing: {task_id} -> {dep}'})
    for start in sorted(task_dep_graph):
        seen: set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            for dep in task_dep_graph.get(node, []):
                if dep == start:
                    errors.append({'path': (idx / 'tasks.tsv').as_posix(), 'issue': f'task dependency cycle includes: {start}'})
                    stack = []
                    break
                if dep not in seen:
                    seen.add(dep)
                    stack.append(dep)

    if (root / 'RESULTS_INDEX.md').exists() and normalized_text(root / 'RESULTS_INDEX.md') != results_index_markdown_text(root):
        warnings.append({'path': (root / 'RESULTS_INDEX.md').as_posix(), 'issue': 'derived RESULTS_INDEX.md is stale; run refresh-indexes'})
    data_assets_status = data_assets_view_status(root)
    if data_assets_status.get('stale'):
        warnings.append({'path': (root / str(data_assets_status.get('path', 'DATA_ASSETS.md'))).as_posix(), 'issue': 'derived DATA_ASSETS view is stale; run refresh-indexes'})
    if (root / 'RUNS_INDEX.tsv').exists() and read_tsv(root / 'RUNS_INDEX.tsv') != read_tsv(idx / 'runs.tsv'):
        warnings.append({'path': (root / 'RUNS_INDEX.tsv').as_posix(), 'issue': 'derived RUNS_INDEX.tsv is stale; run refresh-indexes'})

    primary_location_by_asset = {row.get('asset_id', ''): row for row in asset_location_rows if row.get('role') == 'primary' and row.get('asset_id')}
    for row in asset_rows:
        aid = row.get('asset_id', '')
        primary = primary_location_by_asset.get(aid)
        if not primary:
            warnings.append({'path': (idx / 'asset_locations.tsv').as_posix(), 'issue': f'asset missing primary location row: {aid}'})
            continue
        if row.get('path') and primary.get('path') and row.get('path') != primary.get('path'):
            warnings.append({'path': (idx / 'asset_locations.tsv').as_posix(), 'issue': f'asset primary path mismatch: {aid}'})
        if row.get('checksum') and primary.get('checksum') and row.get('checksum') != primary.get('checksum'):
            warnings.append({'path': (idx / 'asset_locations.tsv').as_posix(), 'issue': f'asset primary checksum mismatch: {aid}'})

    if events_path(root).exists():
        known_ids = {
            'branch': {r.get('branch_id', '') for r in branch_rows},
            'task': {r.get('task_id', '') for r in task_rows},
            'run': {r.get('run_id', '') for r in run_rows},
            'result': {r.get('result_id', '') for r in result_rows},
            'asset': {r.get('asset_id', '') for r in asset_rows},
            'release': {r.get('release_id', '') for r in release_rows if r.get('release_id')},
        }
        for line_no, event in enumerate(read_jsonl(events_path(root)), start=1):
            detail = event.get('detail', {}) if isinstance(event.get('detail'), dict) else {}
            reference_checks = [
                ('branch', 'branch_id', event.get('branch_id') or detail.get('branch_id')),
                ('task', 'task_id', event.get('task_id') or detail.get('task_id')),
                ('run', 'run_id', event.get('run_id') or detail.get('run_id')),
                ('result', 'result_id', event.get('result_id') or detail.get('result_id')),
                ('asset', 'asset_id', detail.get('asset_id')),
                ('release', 'release_id', detail.get('release_id')),
            ]
            for kind, label, value in reference_checks:
                value = str(value or '')
                if value and value not in known_ids[kind]:
                    warnings.append({'path': events_path(root).as_posix(), 'issue': f'event line {line_no} references missing {kind}: {value}'})
            for result_id in [item.strip() for item in str(detail.get('result_ids', '') or '').split(',') if item.strip()]:
                if result_id not in known_ids['result']:
                    warnings.append({'path': events_path(root).as_posix(), 'issue': f'event line {line_no} references missing result: {result_id}'})
        add_journal_snapshot_checks(root, branch_rows, task_rows, run_rows, result_rows, asset_rows, release_rows, warnings)


def repair_step_for_issue(root: Path, item: dict[str, str], severity: str) -> dict[str, Any]:
    issue = item.get('issue', item.get('detail', ''))
    path = item.get('path', '')
    name = item.get('name', '')
    source_path = path
    if path:
        candidate = Path(path)
        if candidate.is_absolute():
            source_path = relpath(root, candidate)
    base = ['python', 'scripts/project_os.py']
    step: dict[str, Any] = {'severity': severity, 'source_path': source_path, 'issue': issue, 'suggested_command': '', 'destructive': False, 'requires_approval': False, 'notes': ''}
    if (
        (path.endswith('.project_os/journals/events.jsonl') and 'missing required harness file' in issue)
        or name == 'events.jsonl'
    ):
        step['suggested_command'] = ' '.join(base + ['restore-journal', '--root', '<project>', '--apply', '--approved'])
        step['requires_approval'] = True
        step['notes'] = 'Creates a missing lifecycle journal and appends journal.restored. It does not overwrite an existing journal or synthesize historical lifecycle events.'
    elif 'stale' in issue or 'header mismatch' in issue or 'derived' in issue:
        step['suggested_command'] = ' '.join(base + ['refresh-indexes', '--root', '<project>'])
    elif 'missing root human entry file' in issue or 'missing required harness file' in issue or 'missing required harness directory' in issue:
        step['suggested_command'] = ' '.join(base + ['init', '--root', '<project>', '--apply'])
        step['requires_approval'] = True
    elif 'points to missing branch' in issue or 'current_branch points' in issue:
        step['suggested_command'] = ' '.join(base + ['list-branches', '--root', '<project>'])
        step['notes'] = 'Then run set-current-branch with a valid active branch id.'
    elif 'points to missing task' in issue:
        step['suggested_command'] = ' '.join(base + ['list-tasks', '--root', '<project>'])
        step['notes'] = 'Then run set-current-task with a valid task id, or clear the pointer manually after review.'
    elif 'points to missing run' in issue:
        step['suggested_command'] = ' '.join(base + ['list-runs', '--root', '<project>'])
        step['notes'] = 'Then run set-current-run with a valid run id, or clear the pointer manually after review.'
    elif 'context manifest' in issue:
        step['suggested_command'] = ' '.join(base + ['add-context', '--root', '<project>', '--task-id', '<task_id>', '--path', '<path>', '--purpose', '<purpose>'])
        step['notes'] = 'If the manifest file itself is missing, create it with the required context rows before rerunning validate.'
    elif 'asset checksum drift' in issue or 'asset_checksum' in item.get('name', ''):
        match = re.search(r'(asset_[A-Za-z0-9_\\-]+|[A-Za-z0-9_\\-]+)$', issue)
        asset_id = match.group(1) if match else '<asset_id>'
        step['suggested_command'] = ' '.join(base + ['checksum-asset', '--root', '<project>', '--asset-id', asset_id])
        step['requires_approval'] = True
        step['notes'] = 'Only add --update after confirming the asset change is intentional.'
    elif 'asset location' in issue or 'asset_location_' in item.get('name', '') or 'asset missing primary location row' in issue or 'asset primary path mismatch' in issue or 'asset primary checksum mismatch' in issue:
        step['suggested_command'] = ' '.join(base + ['verify-external-assets', '--root', '<project>', '--checksum'])
        step['notes'] = 'Review asset_locations.tsv against assets.tsv and external storage roots. If canonical metadata changed intentionally, refresh or externalize again instead of hand-editing drift away.'
    elif 'result path missing' in issue or item.get('name', '').startswith('result_path:'):
        step['suggested_command'] = ' '.join(base + ['show-result', '--root', '<project>', '--result-id', '<result_id>'])
        step['notes'] = 'Regenerate the artifact or register a replacement result; do not delete provenance.'
    elif 'missing current target' in issue or 'duplicate current target' in issue or 'unscoped current result' in issue or 'cross-branch promotion target' in issue:
        step['suggested_command'] = ' '.join(base + ['show-current', '--root', '<project>', '--scope', 'all', '--audit'])
        step['notes'] = 'Review current/project vs current/branches targets, then rerun promote-result with an explicit current/ path if needed.'
    elif 'journal snapshot missing event coverage' in issue:
        step['suggested_command'] = ' '.join(base + ['summarize-state', '--root', '<project>'])
        step['notes'] = 'Review object provenance against events.jsonl. If this is intentional legacy/adopted state, record a decision; do not hand-edit lifecycle events.'
    elif 'session cleanup' in issue or 'session_cleanup_candidates' in item.get('name', ''):
        step['suggested_command'] = ' '.join(base + ['plan-session-cleanup', '--root', '<project>', '--status', 'closed', '--write-report'])
        step['notes'] = 'Report-only session cleanup planning. Review candidates manually; the command does not delete, move, archive, or rewrite session directories.'
    elif 'recovery/crash inspection candidate' in issue or 'recovery_candidates' in item.get('name', ''):
        step['suggested_command'] = ' '.join(base + ['plan-recovery', '--root', '<project>', '--write-report'])
        step['notes'] = 'Report-only recovery planning. Review stale locks, tmp files, malformed journal lines, missing paths, pointer drift, and generated-view drift manually; the command does not replay, roll back, delete tmp files, remove locks, or rewrite canonical state.'
    elif 'hooks config requests active dispatcher' in issue or 'hooks_active_dispatcher_disabled' in item.get('name', ''):
        step['suggested_command'] = ' '.join(base + ['list-hooks', '--root', '<project>'])
        step['notes'] = 'Automatic hooks are intentionally deferred. Keep hooks.enabled=false, hooks.mode=disabled, and hooks.dispatcher=none unless a future opt-in active dispatcher is explicitly approved.'
    elif 'unknown hooks allowed_kinds' in issue or 'hooks_allowed_kinds' in item.get('name', ''):
        step['suggested_command'] = ' '.join(base + ['list-hooks', '--root', '<project>'])
        step['notes'] = 'Review .project_os/config.yaml and keep allowed hook kinds aligned with the implemented manual report handlers.'
    elif 'hooks event source missing' in issue or 'hooks_event_source' in item.get('name', ''):
        if path in {'.project_os/journals/events.jsonl', '<project>/.project_os/journals/events.jsonl'} or path.endswith('/.project_os/journals/events.jsonl') or 'hooks event source missing: .project_os/journals/events.jsonl' in issue:
            step['suggested_command'] = ' '.join(base + ['restore-journal', '--root', '<project>', '--apply', '--approved'])
            step['requires_approval'] = True
            step['notes'] = 'Restores only the missing default event source file. Existing object provenance still needs manual review if journal coverage warnings remain.'
        else:
            step['suggested_command'] = ' '.join(base + ['list-hooks', '--root', '<project>'])
            step['notes'] = 'Configured hooks.event_source is not the default journal path. Review .project_os/config.yaml and either restore the default event_source or create the configured source intentionally.'
    elif item.get('name', '').startswith('codex_adapter:') or 'install-adapters --platforms codex' in issue:
        step['suggested_command'] = ' '.join(base + ['install-adapters', '--root', '<project>', '--platforms', 'codex', '--apply'])
        step['requires_approval'] = True
        step['notes'] = 'Adapter installation updates project entry docs only; run as dry-run first by omitting --apply if adopting an unfamiliar project.'
    elif item.get('name', '').startswith('claude_adapter:') or 'install-adapters --platforms claude' in issue:
        step['suggested_command'] = ' '.join(base + ['install-adapters', '--root', '<project>', '--platforms', 'claude', '--apply'])
        step['requires_approval'] = True
        step['notes'] = 'Adapter installation updates CLAUDE.md only; run as dry-run first by omitting --apply if adopting an unfamiliar project.'
    elif 'release' in issue or item.get('name', '').startswith('release_'):
        step['suggested_command'] = ' '.join(base + ['validate-release', '--root', '<project>', '--release-id', '<release_id>'])
        step['notes'] = 'Rebuild the release only after confirming selected result IDs.'
    elif 'inactive branch has active tasks' in issue:
        step['suggested_command'] = ' '.join(base + ['list-tasks', '--root', '<project>', '--branch-id', '<branch_id>'])
        step['notes'] = 'Close, pause, or move active tasks before treating the branch as archived.'
    elif 'inactive branch has active runs' in issue:
        step['suggested_command'] = ' '.join(base + ['list-runs', '--root', '<project>', '--branch-id', '<branch_id>'])
        step['notes'] = 'Close or archive active runs before treating the branch as archived.'
    elif 'replaced_by' in issue or 'supersede' in issue:
        step['suggested_command'] = ' '.join(base + ['list-results', '--root', '<project>'])
        step['notes'] = 'Fix replacement links with supersede-result --approved after reviewing the result DAG.'
    elif 'dependency' in issue or 'depends_on' in issue:
        step['suggested_command'] = ' '.join(base + ['show-task', '--root', '<project>', '--task-id', '<task_id>'])
        step['notes'] = 'Review task dependencies, then use add-dependency/remove-dependency to repair the DAG.'
    else:
        step['suggested_command'] = ' '.join(base + ['doctor', '--root', '<project>'])
        step['notes'] = 'Manual review required; no safe automatic repair is known.'
    return step


def repair_plan_from_items(root: Path, checks: list[dict[str, Any]], validation_errors: list[dict[str, str]], validation_warnings: list[dict[str, str]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for check in checks:
        if check.get('ok'):
            continue
        item = {'path': check.get('detail', ''), 'issue': check.get('hint') or check.get('name', ''), 'name': check.get('name', '')}
        step = repair_step_for_issue(root, item, str(check.get('severity') or 'warning'))
        key = (step['source_path'], step['suggested_command'])
        if key not in seen:
            steps.append(step); seen.add(key)
    for severity, items in [('error', validation_errors), ('warning', validation_warnings)]:
        for item in items:
            step = repair_step_for_issue(root, item, severity)
            key = (step['source_path'], step['suggested_command'])
            if key not in seen:
                steps.append(step); seen.add(key)
    return steps
