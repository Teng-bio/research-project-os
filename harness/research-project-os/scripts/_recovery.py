from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from _schema import *
from _paths import *
from _project_io import (
    ProjectOSError,
    events_path,
    now_iso,
    print_json,
    read_json,
    read_tsv,
    timestamp,
    write_json,
)
from _views import data_assets_view_status, results_index_markdown_text


RECOVERY_DEFAULT_OUTPUT = '.project_os/exports/recovery'


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return parsed
    except ValueError:
        return None


def path_mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    except OSError:
        return None


def age_seconds(path: Path, now: datetime) -> float | None:
    mtime = path_mtime(path)
    if mtime is None:
        return None
    return max(0.0, (now - mtime).total_seconds())


def pid_running(pid: Any) -> bool | None:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    try:
        os.kill(value, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def read_lock_payload(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding='utf-8', errors='replace').strip()
    except OSError as exc:
        return {}, f'read_error: {exc}'
    if not text:
        return {}, 'empty_lock_file'
    try:
        payload = json.loads(text.splitlines()[0])
    except json.JSONDecodeError as exc:
        return {}, f'malformed_lock_json: {exc}'
    if not isinstance(payload, dict):
        return {}, 'lock_payload_not_object'
    return payload, ''


def inspect_lock(root: Path, *, now: datetime, max_lock_age_seconds: int) -> dict[str, Any]:
    path = project_os(root) / 'runtime' / 'lock'
    if not path.exists():
        return {
            'exists': False,
            'path': relpath(root, path),
            'stale_candidate': False,
            'status': 'missing',
            'policy': 'No advisory lock file is present.',
        }

    payload, parse_error = read_lock_payload(path)
    pid = payload.get('pid') if payload else ''
    running = pid_running(pid) if pid else None
    created_at = parse_time(str(payload.get('created_at', ''))) if payload else None
    mtime_age = age_seconds(path, now)
    created_age = max(0.0, (now - created_at).total_seconds()) if created_at else None
    effective_age = created_age if created_age is not None else mtime_age

    stale = False
    reasons: list[str] = []
    if parse_error:
        stale = True
        reasons.append(parse_error)
    if running is False:
        stale = True
        reasons.append('lock_pid_not_running')
    if effective_age is not None and effective_age > max_lock_age_seconds:
        stale = True
        reasons.append(f'lock_age_exceeds_{max_lock_age_seconds}s')
    if running is True and not stale:
        reasons.append('lock_pid_running')

    return {
        'exists': True,
        'path': relpath(root, path),
        'stale_candidate': stale,
        'status': 'stale_candidate' if stale else 'active_or_recent',
        'pid': '' if pid is None else str(pid),
        'pid_running': running,
        'created_at': str(payload.get('created_at', '')) if payload else '',
        'command': str(payload.get('command', '')) if payload else '',
        'age_seconds': None if effective_age is None else round(effective_age, 3),
        'mtime_age_seconds': None if mtime_age is None else round(mtime_age, 3),
        'reasons': reasons,
        'review_note': 'Report-only. The planner never removes lock files; review running processes before manual cleanup.',
    }


def tmp_target(path: Path) -> Path:
    raw = path.as_posix()
    if raw.endswith('.tmp'):
        return Path(raw[:-4])
    return path.with_name(path.name.replace('.tmp.', '.', 1))


def tmp_file_row(root: Path, path: Path, now: datetime) -> dict[str, Any]:
    target = tmp_target(path)
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {
        'path': relpath(root, path),
        'size_bytes': size,
        'age_seconds': None if age_seconds(path, now) is None else round(float(age_seconds(path, now) or 0.0), 3),
        'mtime': path_mtime(path).isoformat(timespec='seconds') if path_mtime(path) else '',
        'target_path': relpath(root, target),
        'target_exists': target.exists(),
        'review_note': 'Likely interrupted atomic write candidate. Do not delete automatically; compare with target after confirming no writer is active.',
    }


def scan_tmp_files(root: Path, *, now: datetime, max_tmp_files: int) -> dict[str, Any]:
    seen: set[Path] = set()
    candidates: list[Path] = []

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen and path.is_file():
            seen.add(resolved)
            candidates.append(path)

    os_dir = project_os(root)
    if os_dir.exists():
        excluded_roots = [
            (project_os(root) / 'exports' / 'recovery').resolve(),
            (project_os(root) / 'exports' / 'hooks').resolve(),
            (project_os(root) / 'exports' / 'session_cleanup').resolve(),
        ]
        for path in sorted(os_dir.rglob('*')):
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if any(resolved == excluded or excluded in resolved.parents for excluded in excluded_roots):
                continue
            if path.is_file() and (path.name.endswith('.tmp') or '.tmp.' in path.name):
                add(path)
    for path in sorted(root.glob('*.tmp')):
        add(path)
    for name in ROOT_ENTRY_FILES:
        candidate = root / f'{name}.tmp'
        if candidate.exists():
            add(candidate)

    total = len(candidates)
    limit = max(0, int(max_tmp_files))
    selected = candidates[:limit] if limit else []
    return {
        'count': total,
        'truncated': bool(limit and total > limit),
        'max_reported': limit,
        'candidates': [tmp_file_row(root, path, now) for path in selected],
        'policy': 'Temporary file scan is report-only and limited to harness/root atomic-write leftovers.',
    }


def inspect_event_journal(root: Path, *, max_malformed: int = 50) -> dict[str, Any]:
    path = events_path(root)
    payload: dict[str, Any] = {
        'path': relpath(root, path),
        'exists': path.exists(),
        'line_count': 0,
        'valid_event_count': 0,
        'malformed_event_count': 0,
        'missing_key_warning_count': 0,
        'latest_event': '',
        'latest_ts': '',
        'malformed_lines': [],
        'missing_key_warnings': [],
    }
    if not path.exists():
        payload['suggested_command'] = 'python scripts/project_os.py restore-journal --root <project>'
        return payload

    for line_no, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), start=1):
        if not line.strip():
            continue
        payload['line_count'] += 1
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            payload['malformed_event_count'] += 1
            if len(payload['malformed_lines']) < max_malformed:
                payload['malformed_lines'].append({'line_no': line_no, 'error': str(exc), 'raw_excerpt': line[:200]})
            continue
        if not isinstance(item, dict):
            payload['malformed_event_count'] += 1
            if len(payload['malformed_lines']) < max_malformed:
                payload['malformed_lines'].append({'line_no': line_no, 'error': 'event_not_object', 'raw_excerpt': line[:200]})
            continue
        payload['valid_event_count'] += 1
        payload['latest_event'] = str(item.get('event', ''))
        payload['latest_ts'] = str(item.get('ts', ''))
        missing = [key for key in ['ts', 'event', 'actor', 'detail'] if key not in item]
        if missing:
            payload['missing_key_warning_count'] += 1
            if len(payload['missing_key_warnings']) < max_malformed:
                payload['missing_key_warnings'].append({'line_no': line_no, 'missing_keys': missing})
    return payload


def required_paths(root: Path) -> dict[str, Any]:
    os_dir = project_os(root)
    missing_required: list[dict[str, str]] = []
    missing_recommended: list[dict[str, str]] = []

    required_dirs = [
        os_dir,
        os_dir / 'spec',
        os_dir / 'runtime',
        os_dir / 'runtime' / 'sessions',
        os_dir / 'journals',
        os_dir / 'indexes',
        os_dir / 'branches',
    ]
    required_files = [
        os_dir / 'workflow.md',
        os_dir / 'config.yaml',
        os_dir / 'project.json',
        events_path(root),
        os_dir / 'runtime' / 'current_branch',
        os_dir / 'runtime' / 'current_task',
        os_dir / 'runtime' / 'current_run',
        os_dir / 'runtime' / 'current_session',
    ]
    for name in INDEX_HEADERS:
        required_files.append(os_dir / 'indexes' / name)

    for path in required_dirs:
        if not path.exists():
            missing_required.append({'kind': 'dir', 'path': relpath(root, path)})
    for path in required_files:
        if not path.exists():
            missing_required.append({'kind': 'file', 'path': relpath(root, path)})
    for name in ROOT_ENTRY_FILES:
        path = root / name
        if not path.exists():
            missing_recommended.append({'kind': 'root_entry', 'path': name})

    return {
        'missing_required_count': len(missing_required),
        'missing_recommended_count': len(missing_recommended),
        'missing_required': missing_required,
        'missing_recommended': missing_recommended,
    }


def safe_read_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        return read_json(path), ''
    except ProjectOSError as exc:
        return None, str(exc)


def manifest_ids(root: Path, pattern: str, id_field: str) -> tuple[set[str], list[dict[str, str]]]:
    ids: set[str] = set()
    errors: list[dict[str, str]] = []
    for path in sorted(root.glob(pattern)):
        data, error = safe_read_json(path)
        if error:
            errors.append({'path': relpath(root, path), 'issue': error})
            continue
        value = str((data or {}).get(id_field) or path.parent.name)
        if value:
            ids.add(value)
    return ids, errors


def inspect_index_drift(root: Path) -> dict[str, Any]:
    idx = indexes_dir(root)
    drift: list[dict[str, Any]] = []
    manifest_errors: list[dict[str, str]] = []

    branch_manifest_ids, errors = manifest_ids(root, '.project_os/branches/*/branch.json', 'branch_id')
    manifest_errors.extend(errors)
    task_manifest_ids, errors = manifest_ids(root, '.project_os/branches/*/tasks/*/task.json', 'task_id')
    manifest_errors.extend(errors)
    run_manifest_ids: set[str] = set()
    for pattern in ['runs/*/*/RUN_MANIFEST.json', 'analysis_runs/*/*/RUN_MANIFEST.json']:
        ids, errors = manifest_ids(root, pattern, 'run_id')
        run_manifest_ids.update(ids)
        manifest_errors.extend(errors)

    comparisons = [
        ('branches', branch_manifest_ids, {row.get('branch_id', '') for row in read_tsv(idx / 'branches.tsv') if row.get('branch_id')}),
        ('tasks', task_manifest_ids, {row.get('task_id', '') for row in read_tsv(idx / 'tasks.tsv') if row.get('task_id')}),
        ('runs', run_manifest_ids, {row.get('run_id', '') for row in read_tsv(idx / 'runs.tsv') if row.get('run_id')}),
    ]
    for name, manifests, index_ids in comparisons:
        missing_in_index = sorted(manifests - index_ids)
        missing_manifest = sorted(index_ids - manifests)
        if missing_in_index or missing_manifest:
            drift.append({
                'index': f'{name}.tsv',
                'manifest_count': len(manifests),
                'index_count': len(index_ids),
                'missing_in_index': missing_in_index,
                'missing_manifest': missing_manifest,
                'suggested_command': 'python scripts/project_os.py refresh-indexes --root <project>',
            })

    return {
        'drift_count': len(drift),
        'manifest_error_count': len(manifest_errors),
        'drift': drift,
        'manifest_errors': manifest_errors,
        'policy': 'Index drift scan compares manifest IDs with canonical index rows; it does not rewrite indexes.',
    }


def inspect_pointers(root: Path) -> dict[str, Any]:
    os_dir = project_os(root)
    issues: list[dict[str, str]] = []
    branch_ids = {row.get('branch_id', '') for row in read_tsv(indexes_dir(root) / 'branches.tsv') if row.get('branch_id')}
    task_ids = {row.get('task_id', '') for row in read_tsv(indexes_dir(root) / 'tasks.tsv') if row.get('task_id')}
    run_ids = {row.get('run_id', '') for row in read_tsv(indexes_dir(root) / 'runs.tsv') if row.get('run_id')}

    for name, known, label in [
        ('current_branch', branch_ids, 'branch'),
        ('current_task', task_ids, 'task'),
        ('current_run', run_ids, 'run'),
    ]:
        path = os_dir / 'runtime' / name
        if not path.exists():
            continue
        value = path.read_text(encoding='utf-8', errors='replace').strip()
        if value and value not in known:
            issues.append({'pointer': relpath(root, path), 'value': value, 'issue': f'points_to_missing_{label}'})

    current_session_path = os_dir / 'runtime' / 'current_session'
    if current_session_path.exists():
        session_id = current_session_path.read_text(encoding='utf-8', errors='replace').strip()
        if session_id and not (os_dir / 'runtime' / 'sessions' / session_id / 'session.json').exists():
            issues.append({'pointer': relpath(root, current_session_path), 'value': session_id, 'issue': 'points_to_missing_session'})
    return {'issue_count': len(issues), 'issues': issues}


def canonical_paths(root: Path) -> list[Path]:
    os_dir = project_os(root)
    paths: list[Path] = [os_dir / 'project.json', events_path(root)]
    for name in INDEX_HEADERS:
        paths.append(indexes_dir(root) / name)
    for pattern in ['.project_os/branches/*/branch.json', '.project_os/branches/*/tasks/*/task.json', '.project_os/runtime/sessions/*/session.json', 'runs/*/*/RUN_MANIFEST.json', 'analysis_runs/*/*/RUN_MANIFEST.json']:
        paths.extend(root.glob(pattern))
    return [path for path in paths if path.exists()]


def latest_mtime(paths: list[Path]) -> datetime | None:
    mtimes = [path_mtime(path) for path in paths]
    valid = [item for item in mtimes if item is not None]
    return max(valid) if valid else None


def inspect_generated_views(root: Path, *, include_dashboard_staleness: bool = True) -> dict[str, Any]:
    stale: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    try:
        if (root / 'RESULTS_INDEX.md').exists() and (root / 'RESULTS_INDEX.md').read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n') != results_index_markdown_text(root):
            stale.append({'path': 'RESULTS_INDEX.md', 'issue': 'derived_results_index_stale', 'suggested_command': 'python scripts/project_os.py refresh-indexes --root <project>'})
    except Exception as exc:  # generated-view inspection must not block recovery planning
        errors.append({'path': 'RESULTS_INDEX.md', 'issue': str(exc)})
    try:
        status = data_assets_view_status(root)
        if status.get('stale'):
            stale.append({'path': str(status.get('path', 'DATA_ASSETS.md')), 'issue': 'derived_data_assets_stale', 'suggested_command': 'python scripts/project_os.py refresh-indexes --root <project>'})
    except Exception as exc:
        errors.append({'path': 'DATA_ASSETS view', 'issue': str(exc)})
    try:
        if (root / 'RUNS_INDEX.tsv').exists() and read_tsv(root / 'RUNS_INDEX.tsv') != read_tsv(indexes_dir(root) / 'runs.tsv'):
            stale.append({'path': 'RUNS_INDEX.tsv', 'issue': 'derived_runs_index_stale', 'suggested_command': 'python scripts/project_os.py refresh-indexes --root <project>'})
    except Exception as exc:
        errors.append({'path': 'RUNS_INDEX.tsv', 'issue': str(exc)})

    if include_dashboard_staleness:
        # Do not use events.jsonl itself as the dashboard freshness anchor here:
        # export-dashboard records an export.created event after writing the
        # generated files, so including the journal would make every dashboard
        # immediately look stale. Canonical registries/manifests are enough for
        # this advisory recovery view.
        dashboard_anchors = [path for path in canonical_paths(root) if path != events_path(root)]
        newest = latest_mtime(dashboard_anchors)
        if newest is not None:
            for path in [project_os(root) / 'exports' / 'dashboard.json', project_os(root) / 'exports' / 'dashboard.html', project_os(root) / 'exports' / 'dashboard.sqlite']:
                mtime = path_mtime(path) if path.exists() else None
                if mtime is not None and mtime < newest:
                    stale.append({
                        'path': relpath(root, path),
                        'issue': 'generated_dashboard_older_than_canonical_state',
                        'suggested_command': 'python scripts/project_os.py export-dashboard --root <project> --apply',
                    })

    return {
        'stale_count': len(stale),
        'error_count': len(errors),
        'stale': stale,
        'errors': errors,
        'policy': 'Generated view drift is advisory; generated files are not canonical state.',
    }


def suggested_commands(summary: dict[str, Any], sections: dict[str, Any]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = [
        {
            'reason': 'baseline_health_review',
            'command': 'python scripts/project_os.py doctor --root <project> --repair-plan',
            'writes': False,
            'requires_approval': False,
        },
        {
            'reason': 'schema_and_pointer_validation',
            'command': 'python scripts/project_os.py validate --root <project>',
            'writes': False,
            'requires_approval': False,
        },
    ]
    journal = sections.get('event_journal', {})
    if not journal.get('exists'):
        suggestions.append({
            'reason': 'missing_event_journal',
            'command': 'python scripts/project_os.py restore-journal --root <project> --apply --approved',
            'writes': True,
            'requires_approval': True,
            'notes': 'Creates only the missing events.jsonl and journal.restored; no historical replay.',
        })
    if summary.get('index_drift_count') or summary.get('stale_generated_view_count'):
        suggestions.append({
            'reason': 'index_or_root_view_drift',
            'command': 'python scripts/project_os.py refresh-indexes --root <project>',
            'writes': True,
            'requires_approval': False,
            'notes': 'Regenerates indexes/root derived views through the CLI; review first on unfamiliar projects.',
        })
    if summary.get('stale_dashboard_count'):
        suggestions.append({
            'reason': 'generated_dashboard_stale',
            'command': 'python scripts/project_os.py export-dashboard --root <project> --apply',
            'writes': True,
            'requires_approval': False,
            'notes': 'Writes generated inspection views only, not canonical state.',
        })
    if summary.get('stale_lock_candidates'):
        suggestions.append({
            'reason': 'stale_lock_candidate',
            'command': 'ps -p <pid> -o pid,ppid,etime,command',
            'writes': False,
            'requires_approval': False,
            'notes': 'Review process state and lock payload manually; this planner never removes locks.',
        })
    if summary.get('tmp_file_count'):
        suggestions.append({
            'reason': 'tmp_file_candidates',
            'command': 'manual review only',
            'writes': False,
            'requires_approval': True,
            'notes': 'Compare *.tmp with targets after confirming no writer is active; no automatic deletion is provided.',
        })
    if summary.get('malformed_event_count'):
        suggestions.append({
            'reason': 'malformed_event_lines',
            'command': 'manual journal review only',
            'writes': False,
            'requires_approval': True,
            'notes': 'Do not synthesize or rewrite lifecycle events automatically; preserve the original journal for audit.',
        })
    return suggestions


def build_recovery_plan(root: Path, *, max_lock_age_seconds: int = 300, max_tmp_files: int = 200, include_dashboard_staleness: bool = True) -> dict[str, Any]:
    now = datetime.now().astimezone()
    os_dir = project_os(root)
    sections: dict[str, Any] = {
        'lock': inspect_lock(root, now=now, max_lock_age_seconds=max(0, int(max_lock_age_seconds))),
        'tmp_files': scan_tmp_files(root, now=now, max_tmp_files=max(0, int(max_tmp_files))),
        'event_journal': inspect_event_journal(root),
        'required_paths': required_paths(root),
        'pointers': inspect_pointers(root),
        'index_drift': inspect_index_drift(root),
        'generated_views': inspect_generated_views(root, include_dashboard_staleness=include_dashboard_staleness),
    }
    stale_dashboard_count = len([
        item for item in sections['generated_views'].get('stale', [])
        if str(item.get('issue', '')).startswith('generated_dashboard')
    ])
    summary = {
        'initialized': (os_dir / 'workflow.md').exists(),
        'stale_lock_candidates': 1 if sections['lock'].get('stale_candidate') else 0,
        'tmp_file_count': int(sections['tmp_files'].get('count', 0) or 0),
        'malformed_event_count': int(sections['event_journal'].get('malformed_event_count', 0) or 0),
        'missing_required_count': int(sections['required_paths'].get('missing_required_count', 0) or 0),
        'missing_recommended_count': int(sections['required_paths'].get('missing_recommended_count', 0) or 0),
        'pointer_issue_count': int(sections['pointers'].get('issue_count', 0) or 0),
        'index_drift_count': int(sections['index_drift'].get('drift_count', 0) or 0),
        'manifest_error_count': int(sections['index_drift'].get('manifest_error_count', 0) or 0),
        'stale_generated_view_count': int(sections['generated_views'].get('stale_count', 0) or 0),
        'stale_dashboard_count': stale_dashboard_count,
    }
    summary['total_recovery_candidates'] = (
        summary['stale_lock_candidates']
        + summary['tmp_file_count']
        + summary['malformed_event_count']
        + summary['missing_required_count']
        + summary['pointer_issue_count']
        + summary['index_drift_count']
        + summary['manifest_error_count']
        + summary['stale_generated_view_count']
    )
    return {
        'root': root.as_posix(),
        'generated_at': now_iso(),
        'summary': summary,
        **sections,
        'suggested_commands': suggested_commands(summary, sections),
        'policy': {
            'mode': 'dry_run_report_only',
            'canonical_state_unchanged': True,
            'automatic_lock_removal': False,
            'automatic_tmp_delete': False,
            'automatic_replay': False,
            'automatic_rollback': False,
            'notes': [
                'This is a crash/recovery inspection foundation, not full WAL replay.',
                'The planner reports candidates and suggests review commands only.',
                'Any future repair/replay/cleanup operation must remain explicit, reviewed, approval-gated, and validation-gated.',
            ],
        },
    }


def command_plan_recovery(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    plan = build_recovery_plan(
        root,
        max_lock_age_seconds=int(args.max_lock_age_seconds or 0),
        max_tmp_files=int(args.max_tmp_files or 0),
    )
    if args.write_report:
        if not project_os(root).exists():
            raise ProjectOSError('Cannot write recovery report because .project_os/ is missing; run plan-recovery without --write-report or initialize the harness first.')
        output_raw = args.output or RECOVERY_DEFAULT_OUTPUT
        output = Path(output_raw).expanduser()
        if not output.is_absolute():
            output = root / output
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / f'recovery_plan_{timestamp()}.json'
        write_json(report_path, plan)
        plan['written_report'] = relpath(root, report_path)
        plan['policy']['canonical_state_unchanged'] = True
        plan['policy']['written_report_is_generated_view'] = True
    print_json(plan)
    return 0
