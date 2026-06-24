from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _schema import *
from _paths import *
from _project_io import *
from _integrity import add_integrity_checks, repair_plan_from_items, validate_context_manifest, validate_headers, validate_unique_tsv_key
from _assets import asset_location_path, asset_path_from_row, boolish, checksum_path
from _project_branch import branch_row
from _task_run import find_run_manifest, task_json_path
from _sessions import build_session_cleanup_plan, validate_sessions
from _hooks import HOOK_KINDS, parse_hooks_config
from _recovery import build_recovery_plan


def hooks_config_requests_active_dispatcher(config: dict[str, Any]) -> bool:
    mode = str(config.get('mode', '')).lower()
    dispatcher = str(config.get('dispatcher', '')).lower()
    return bool(config.get('enabled')) or mode not in {'', 'disabled'} or dispatcher not in {'', 'none'}


def hooks_event_source_path(root: Path, config: dict[str, Any]) -> Path:
    source = Path(str(config.get('event_source') or '.project_os/journals/events.jsonl')).expanduser()
    return source if source.is_absolute() else root / source


def command_validate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    os_dir = project_os(root)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    for path in [os_dir / 'workflow.md', os_dir / 'config.yaml', os_dir / 'project.json', events_path(root)]:
        if not path.exists():
            errors.append({'path': path.as_posix(), 'issue': 'missing required harness file'})

    if (os_dir / 'project.json').exists():
        project = read_json(os_dir / 'project.json')
        for field in PROJECT_REQUIRED_FIELDS:
            if field not in project:
                errors.append({'path': (os_dir / 'project.json').as_posix(), 'issue': f'missing project field: {field}'})

    for subdir in ['spec', 'runtime', 'indexes', 'branches', 'journals']:
        if not (os_dir / subdir).exists():
            errors.append({'path': (os_dir / subdir).as_posix(), 'issue': 'missing required harness directory'})

    for pointer in ['current_branch', 'current_task', 'current_run']:
        if not (os_dir / 'runtime' / pointer).exists():
            errors.append({'path': (os_dir / 'runtime' / pointer).as_posix(), 'issue': 'missing runtime pointer'})
    if (os_dir / 'runtime').exists() and not (os_dir / 'runtime' / 'current_session').exists():
        warnings.append({'path': (os_dir / 'runtime' / 'current_session').as_posix(), 'issue': 'missing current_session pointer; sessionized focus will fall back to global pointers'})

    for name, headers in INDEX_HEADERS.items():
        validate_headers(os_dir / 'indexes' / name, headers, errors)

    for name, key in [
        ('branches.tsv', 'branch_id'),
        ('tasks.tsv', 'task_id'),
        ('runs.tsv', 'run_id'),
        ('results.tsv', 'result_id'),
        ('assets.tsv', 'asset_id'),
        ('asset_locations.tsv', 'location_id'),
        ('releases.tsv', 'release_id'),
    ]:
        if (os_dir / 'indexes' / name).exists():
            validate_unique_tsv_key(os_dir / 'indexes' / name, key, errors)

    for name in ROOT_ENTRY_FILES:
        if not (root / name).exists():
            warnings.append({'path': (root / name).as_posix(), 'issue': 'missing root human entry file'})

    b_id = current_pointer(root, 'current_branch') if (os_dir / 'runtime').exists() else ''
    if b_id and not branch_row(root, b_id):
        errors.append({'path': (os_dir / 'runtime' / 'current_branch').as_posix(), 'issue': f'points to missing branch: {b_id}'})

    for branch_file in sorted((os_dir / 'branches').glob('*/branch.json')):
        try:
            branch = read_json(branch_file)
        except ProjectOSError as exc:
            errors.append({'path': branch_file.as_posix(), 'issue': str(exc)})
            continue
        for field in BRANCH_REQUIRED_FIELDS:
            if field not in branch:
                errors.append({'path': branch_file.as_posix(), 'issue': f'missing branch field: {field}'})
        if branch.get('status') and branch.get('status') not in BRANCH_STATUSES:
            warnings.append({'path': branch_file.as_posix(), 'issue': f'nonstandard branch status: {branch.get("status")}'})

    current_task = current_pointer(root, 'current_task') if (os_dir / 'runtime').exists() else ''
    if current_task and not task_json_path(root, current_task):
        errors.append({'path': (os_dir / 'runtime' / 'current_task').as_posix(), 'issue': f'points to missing task: {current_task}'})

    current_run = current_pointer(root, 'current_run') if (os_dir / 'runtime').exists() else ''
    if current_run and not find_run_manifest(root, current_run):
        errors.append({'path': (os_dir / 'runtime' / 'current_run').as_posix(), 'issue': f'points to missing run: {current_run}'})

    for task_file in sorted((os_dir / 'branches').glob('*/tasks/*/task.json')):
        try:
            task = read_json(task_file)
        except ProjectOSError as exc:
            errors.append({'path': task_file.as_posix(), 'issue': str(exc)})
            continue
        for field in TASK_REQUIRED_FIELDS:
            if field not in task:
                errors.append({'path': task_file.as_posix(), 'issue': f'missing task field: {field}'})
        if task.get('status') and task.get('status') not in TASK_STATUSES:
            warnings.append({'path': task_file.as_posix(), 'issue': f'nonstandard task status: {task.get("status")}'})
        if task.get('branch_id') and task.get('branch_id') != task_file.parents[2].name:
            errors.append({'path': task_file.as_posix(), 'issue': 'task branch_id does not match path'})
        validate_context_manifest(root, task_file.parent / task.get('context_manifest', 'context_manifest.jsonl'), errors, warnings)

    for run_base in [root / 'runs', root / 'analysis_runs']:
        if run_base.exists():
            for manifest_file in sorted(run_base.glob('*/*/RUN_MANIFEST.json')):
                try:
                    manifest = read_json(manifest_file)
                except ProjectOSError as exc:
                    errors.append({'path': manifest_file.as_posix(), 'issue': str(exc)})
                    continue
                for field in RUN_REQUIRED_FIELDS:
                    if field not in manifest:
                        errors.append({'path': manifest_file.as_posix(), 'issue': f'missing run field: {field}'})
                if manifest.get('status') and manifest.get('status') not in RUN_STATUSES:
                    warnings.append({'path': manifest_file.as_posix(), 'issue': f'nonstandard run status: {manifest.get("status")}'})
                if manifest.get('task_id') and not task_json_path(root, str(manifest['task_id']), branch_id=str(manifest.get('branch_id') or '')):
                    warnings.append({'path': manifest_file.as_posix(), 'issue': f'run task_id not found in branch tasks: {manifest.get("task_id")}'})

    for row in read_tsv(os_dir / 'indexes' / 'results.tsv') if (os_dir / 'indexes' / 'results.tsv').exists() else []:
        if row.get('status') and row['status'] not in RESULT_STATUSES:
            warnings.append({'path': (os_dir / 'indexes' / 'results.tsv').as_posix(), 'issue': f'nonstandard result status: {row.get("status")}'})
        if row.get('path'):
            target, _ = project_relative_or_absolute(root, row['path'])
            if not target.exists():
                warnings.append({'path': (os_dir / 'indexes' / 'results.tsv').as_posix(), 'issue': f'result path missing: {row.get("path")}'})

    asset_ids = {row.get('asset_id', '') for row in read_tsv(os_dir / 'indexes' / 'assets.tsv')} if (os_dir / 'indexes' / 'assets.tsv').exists() else set()
    run_ids = {row.get('run_id', '') for row in read_tsv(os_dir / 'indexes' / 'runs.tsv')} if (os_dir / 'indexes' / 'runs.tsv').exists() else set()

    for row in read_tsv(os_dir / 'indexes' / 'assets.tsv') if (os_dir / 'indexes' / 'assets.tsv').exists() else []:
        if row.get('status') and row['status'] not in ASSET_STATUSES:
            warnings.append({'path': (os_dir / 'indexes' / 'assets.tsv').as_posix(), 'issue': f'nonstandard asset status: {row.get("status")}'})
        target = asset_path_from_row(root, row)
        if target and not target.exists() and row.get('status') not in {'unavailable'}:
            warnings.append({'path': (os_dir / 'indexes' / 'assets.tsv').as_posix(), 'issue': f'asset path missing: {row.get("asset_id")} {row.get("path")}'})
        if target and target.exists() and boolish(row.get('immutable')) and row.get('checksum'):
            current = checksum_path(target)
            if current != row.get('checksum'):
                warnings.append({'path': (os_dir / 'indexes' / 'assets.tsv').as_posix(), 'issue': f'immutable asset checksum drift: {row.get("asset_id")}'})

    for row in read_tsv(os_dir / 'indexes' / 'asset_locations.tsv') if (os_dir / 'indexes' / 'asset_locations.tsv').exists() else []:
        if row.get('asset_id') and row.get('asset_id') not in asset_ids:
            warnings.append({'path': (os_dir / 'indexes' / 'asset_locations.tsv').as_posix(), 'issue': f'asset_locations references missing asset: {row.get("asset_id")}'})
        if row.get('role') and row.get('role') not in ASSET_LOCATION_ROLES:
            warnings.append({'path': (os_dir / 'indexes' / 'asset_locations.tsv').as_posix(), 'issue': f'nonstandard asset location role: {row.get("role")}'})
        if row.get('status') and row.get('status') not in ASSET_LOCATION_STATUSES:
            warnings.append({'path': (os_dir / 'indexes' / 'asset_locations.tsv').as_posix(), 'issue': f'nonstandard asset location status: {row.get("status")}'})
        target = asset_location_path(root, row)
        if target and not target.exists() and row.get('status') == 'available':
            warnings.append({'path': (os_dir / 'indexes' / 'asset_locations.tsv').as_posix(), 'issue': f'asset location marked available but path missing: {row.get("location_id")}'})
        if target and target.exists() and row.get('checksum'):
            current = checksum_path(target)
            if current != row.get('checksum'):
                warnings.append({'path': (os_dir / 'indexes' / 'asset_locations.tsv').as_posix(), 'issue': f'asset location checksum drift: {row.get("location_id")}'})

    for row in read_tsv(os_dir / 'indexes' / 'asset_usage.tsv') if (os_dir / 'indexes' / 'asset_usage.tsv').exists() else []:
        if row.get('asset_id') and row.get('asset_id') not in asset_ids:
            warnings.append({'path': (os_dir / 'indexes' / 'asset_usage.tsv').as_posix(), 'issue': f'asset_usage references missing asset: {row.get("asset_id")}'})
        if row.get('run_id') and row.get('run_id') not in run_ids:
            warnings.append({'path': (os_dir / 'indexes' / 'asset_usage.tsv').as_posix(), 'issue': f'asset_usage references missing run: {row.get("run_id")}'})

    for row in read_tsv(os_dir / 'indexes' / 'releases.tsv') if (os_dir / 'indexes' / 'releases.tsv').exists() else []:
        if row.get('status') and row['status'] not in RELEASE_STATUSES:
            warnings.append({'path': (os_dir / 'indexes' / 'releases.tsv').as_posix(), 'issue': f'nonstandard release status: {row.get("status")}'})
        if row.get('path') and not (root / row['path']).exists():
            warnings.append({'path': (os_dir / 'indexes' / 'releases.tsv').as_posix(), 'issue': f'release path missing: {row.get("release_id")} {row.get("path")}'})

    if events_path(root).exists():
        for idx, event in enumerate(read_jsonl(events_path(root)), start=1):
            if event.get('_error'):
                errors.append({'path': events_path(root).as_posix(), 'issue': f'event line {idx}: malformed JSONL'})
            for key in ['ts', 'event', 'actor', 'detail']:
                if key not in event:
                    warnings.append({'path': events_path(root).as_posix(), 'issue': f'event line {idx}: missing key {key}'})

    hooks_config = parse_hooks_config(root)
    if hooks_config.get('exists'):
        if hooks_config_requests_active_dispatcher(hooks_config):
            warnings.append({'path': str(hooks_config.get('path', '.project_os/config.yaml')), 'issue': 'hooks config requests active dispatcher, but automatic hooks are disabled in this harness build'})
        for kind in hooks_config.get('allowed_kinds', []):
            if kind not in HOOK_KINDS:
                warnings.append({'path': str(hooks_config.get('path', '.project_os/config.yaml')), 'issue': f'unknown hooks allowed_kinds entry: {kind}'})
        configured_event_source = hooks_event_source_path(root, hooks_config)
        if not configured_event_source.exists():
            warnings.append({'path': str(hooks_config.get('path', '.project_os/config.yaml')), 'issue': f'hooks event source missing: {hooks_config.get("event_source")}'})

    validate_sessions(root, errors, warnings)
    add_integrity_checks(root, errors, warnings)
    payload = {
        'root': root.as_posix(),
        'errors': len(errors),
        'warnings': len(warnings),
        'error_items': errors,
        'warning_items': warnings,
    }
    print_json(payload)
    return 1 if errors else 0


def command_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    os_dir = project_os(root)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, hint: str = '', severity: str = 'error') -> None:
        checks.append({'name': name, 'ok': ok, 'severity': severity, 'detail': detail, 'hint': hint})

    add('harness', (os_dir / 'workflow.md').exists(), f'{OS_DIR}/workflow.md', 'Run project_os.py new-project --apply')
    for path, hint in [
        (os_dir / 'project.json', 'Run project_os.py init --apply'),
        (events_path(root), 'Run project_os.py restore-journal --apply --approved after review if only the event journal is missing'),
    ]:
        add(path.name, path.exists(), relpath(root, path), hint)
    for name in ROOT_ENTRY_FILES:
        add(f'entry:{name}', (root / name).exists(), name, 'Run project_os.py init --apply', 'warning')
    for pointer in ['current_branch', 'current_task', 'current_run']:
        add(f'pointer:{pointer}', (os_dir / 'runtime' / pointer).exists(), relpath(root, os_dir / 'runtime' / pointer), 'Run project_os.py init --apply')
    add('pointer:current_session', (os_dir / 'runtime' / 'current_session').exists(), relpath(root, os_dir / 'runtime' / 'current_session'), 'Run project_os.py init --apply or migrate-branch-first --apply', 'warning')

    b_id = current_pointer(root, 'current_branch') if (os_dir / 'runtime' / 'current_branch').exists() else ''
    add('current_branch_target', not b_id or branch_row(root, b_id) is not None, b_id or '(none)', 'Set a valid current branch')

    for row in read_tsv(os_dir / 'indexes' / 'branches.tsv') if (os_dir / 'indexes' / 'branches.tsv').exists() else []:
        add(
            f'branch_workspace:{row.get("branch_id")}',
            (root / row.get('branch_path', '') / 'branch.json').exists(),
            row.get('branch_path', ''),
            'Recreate branch workspace or fix branches.tsv',
        )

    current_task = current_pointer(root, 'current_task') if (os_dir / 'runtime' / 'current_task').exists() else ''
    add('current_task_target', not current_task or task_json_path(root, current_task) is not None, current_task or '(none)', 'Set a valid current task or clear pointer')

    current_run = current_pointer(root, 'current_run') if (os_dir / 'runtime' / 'current_run').exists() else ''
    add('current_run_target', not current_run or find_run_manifest(root, current_run) is not None, current_run or '(none)', 'Set a valid current run or clear pointer')

    agents = root / 'AGENTS.md'
    agents_has_block = agents.exists() and PROJECT_OS_BLOCK_START in agents.read_text(encoding='utf-8', errors='replace')
    add('codex_adapter:AGENTS', agents_has_block, 'AGENTS.md project-os block', 'Run project_os.py install-adapters --platforms codex --apply', 'warning')

    claude = root / 'CLAUDE.md'
    claude_has_block = claude.exists() and PROJECT_OS_BLOCK_START in claude.read_text(encoding='utf-8', errors='replace')
    add('claude_adapter:CLAUDE', claude_has_block, 'CLAUDE.md project-os block', 'Run project_os.py install-adapters --platforms claude --apply', 'warning')

    hooks_config = parse_hooks_config(root)
    hooks_event_source = hooks_event_source_path(root, hooks_config)
    add('hooks_config', bool(hooks_config.get('exists')), str(hooks_config.get('path', '.project_os/config.yaml')), 'Run project_os.py init --apply or restore .project_os/config.yaml', 'warning')
    add(
        'hooks_active_dispatcher_disabled',
        not hooks_config_requests_active_dispatcher(hooks_config),
        f"enabled={hooks_config.get('enabled')} mode={hooks_config.get('mode')} dispatcher={hooks_config.get('dispatcher')}",
        'Keep hooks.enabled=false, hooks.mode=disabled, and hooks.dispatcher=none until active hooks are explicitly designed and approved.',
        'warning',
    )
    unknown_hook_kinds = [kind for kind in hooks_config.get('allowed_kinds', []) if kind not in HOOK_KINDS]
    add(
        'hooks_allowed_kinds',
        not unknown_hook_kinds,
        ','.join(unknown_hook_kinds) or '(all known)',
        f'Use only known hook kinds: {", ".join(HOOK_KINDS)}',
        'warning',
    )
    add(
        'hooks_event_source',
        hooks_event_source.exists(),
        relpath(root, hooks_event_source) if hooks_event_source.exists() else str(hooks_config.get('event_source') or '.project_os/journals/events.jsonl'),
        'Run project_os.py init --apply or restore .project_os/journals/events.jsonl; hooks are report-only and do not replace the event journal.',
        'warning',
    )

    for row in read_tsv(os_dir / 'indexes' / 'results.tsv') if (os_dir / 'indexes' / 'results.tsv').exists() else []:
        if row.get('path'):
            target, _ = project_relative_or_absolute(root, row['path'])
            add(f'result_path:{row.get("result_id")}', target.exists(), row['path'], 'Regenerate/register a valid result path', 'warning')

    for row in read_tsv(os_dir / 'indexes' / 'assets.tsv') if (os_dir / 'indexes' / 'assets.tsv').exists() else []:
        target = asset_path_from_row(root, row)
        if target:
            add(f'asset_path:{row.get("asset_id")}', target.exists() or row.get('status') == 'unavailable', row.get('path', ''), 'Update asset path/status or re-register asset', 'warning')
            if target.exists() and boolish(row.get('immutable')) and row.get('checksum'):
                add(f'asset_checksum:{row.get("asset_id")}', checksum_path(target) == row.get('checksum'), row.get('path', ''), 'Run checksum-asset --asset-id <id> --update only after verifying intentional change', 'warning')
    for row in read_tsv(os_dir / 'indexes' / 'asset_locations.tsv') if (os_dir / 'indexes' / 'asset_locations.tsv').exists() else []:
        target = asset_location_path(root, row)
        if target:
            add(f'asset_location_path:{row.get("location_id")}', target.exists() or row.get('status') != 'available', row.get('path', ''), 'Update location status/path or verify the external storage root', 'warning')
            if target.exists() and row.get('checksum'):
                add(f'asset_location_checksum:{row.get("location_id")}', checksum_path(target) == row.get('checksum'), row.get('path', ''), 'Run verify-external-assets --checksum and update location metadata only after review', 'warning')

    for row in read_tsv(os_dir / 'indexes' / 'releases.tsv') if (os_dir / 'indexes' / 'releases.tsv').exists() else []:
        rdir = root / row.get('path', '')
        add(f'release_path:{row.get("release_id")}', rdir.exists(), row.get('path', ''), 'Rebuild release or fix releases.tsv', 'warning')
        if rdir.exists():
            for name in ['README.md', 'MANIFEST.tsv', 'CHECKSUMS.tsv']:
                add(f'release_file:{row.get("release_id")}:{name}', (rdir / name).exists(), relpath(root, rdir / name), 'Run validate-release or rebuild release', 'warning')

    validation_errors: list[dict[str, str]] = []
    validation_warnings: list[dict[str, str]] = []
    if (os_dir / 'indexes').exists():
        for name, headers in INDEX_HEADERS.items():
            validate_headers(os_dir / 'indexes' / name, headers, validation_errors)
        for name, key in [
            ('branches.tsv', 'branch_id'),
            ('tasks.tsv', 'task_id'),
            ('runs.tsv', 'run_id'),
            ('results.tsv', 'result_id'),
            ('assets.tsv', 'asset_id'),
            ('asset_locations.tsv', 'location_id'),
            ('releases.tsv', 'release_id'),
        ]:
            if (os_dir / 'indexes' / name).exists():
                validate_unique_tsv_key(os_dir / 'indexes' / name, key, validation_errors)
        validate_sessions(root, validation_errors, validation_warnings)
        add_integrity_checks(root, validation_errors, validation_warnings)

    if (os_dir / 'runtime' / 'sessions').exists():
        cleanup_plan = build_session_cleanup_plan(root, statuses=['closed'], min_age_days=0, include_current=False)
        cleanup_count = int(cleanup_plan.get('candidate_count', 0) or 0)
        add(
            'session_cleanup_candidates',
            cleanup_count == 0,
            f'{cleanup_count} closed session cleanup candidate(s)',
            'Run project_os.py plan-session-cleanup --status closed --write-report to review; this is report-only and does not delete/move sessions.',
            'warning',
        )

    recovery_plan = build_recovery_plan(root)
    recovery_summary = recovery_plan.get('summary', {}) if isinstance(recovery_plan.get('summary', {}), dict) else {}
    recovery_count = int(recovery_summary.get('total_recovery_candidates', 0) or 0)
    add(
        'recovery_candidates',
        recovery_count == 0,
        f'{recovery_count} recovery/crash inspection candidate(s)',
        'Run project_os.py plan-recovery --root <project> --write-report to review; this is report-only and never replays, rolls back, deletes tmp files, or removes locks.',
        'warning',
    )

    ok = (not validation_errors) and all(item['ok'] or item['severity'] == 'warning' for item in checks)
    payload: dict[str, Any] = {'root': root.as_posix(), 'ok': ok, 'checks': checks}
    if validation_errors or validation_warnings:
        payload['validation_errors'] = validation_errors
        payload['validation_warnings'] = validation_warnings
    if args.repair_plan:
        payload['repair_plan'] = repair_plan_from_items(root, checks, validation_errors, validation_warnings)
        payload['repair_plan_policy'] = 'Suggestions are dry-run/manual by default; destructive or provenance-changing actions require explicit user approval.'
    print_json(payload)
    return 0 if ok else 1
