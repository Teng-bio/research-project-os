from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from _schema import (
    INDEX_HEADERS,
    OS_DIR,
    RELEASE_STATUSES,
    RESULT_LINK_HEADERS,
    RESULT_STATUSES,
    RESULT_TYPES,
)
from _paths import indexes_dir, project_os, project_relative_or_absolute, relpath
from _project_io import (
    ProjectOSError,
    append_event,
    now_iso,
    print_json,
    read_json,
    read_tsv,
    slugify,
    timestamp,
    upsert_tsv,
    write_json,
    write_tsv,
)
from _task_run import current_branch, find_run_manifest, task_dir
from _views import current_result_views, promotion_audit, refresh_results_index_markdown


def ensure_initialized(root: Path) -> None:
    if not (project_os(root) / 'workflow.md').exists():
        raise ProjectOSError(f'Missing {OS_DIR}/workflow.md. Run init first.')


def checksum_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def checksum_path(path: Path) -> str:
    if path.is_file():
        return checksum_file(path)
    h = hashlib.sha256()
    for item in sorted(p for p in path.rglob('*') if p.is_file()):
        rel = item.relative_to(path).as_posix().encode()
        h.update(rel + b'\0')
        with item.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                h.update(chunk)
    return h.hexdigest()


def command_register_result(args: Any) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    if args.status not in RESULT_STATUSES:
        raise ProjectOSError(f'Invalid result status: {args.status}')
    if args.type not in RESULT_TYPES:
        raise ProjectOSError(f'Invalid result type: {args.type}')
    if args.status in {'accepted', 'current', 'release'} and not args.approved:
        raise ProjectOSError('accepted/current/release registration requires --approved')
    manifest_path = find_run_manifest(root, args.run_id)
    if not manifest_path:
        raise ProjectOSError(f'Missing run: {args.run_id}')
    manifest = read_json(manifest_path)
    branch_id = str(manifest.get('branch_id') or current_branch(root))
    task_id = str(manifest.get('task_id') or '')
    source_path, stored_path = project_relative_or_absolute(root, args.path)
    if not source_path.exists() and not args.allow_missing:
        raise ProjectOSError(f'Result path does not exist: {source_path}')
    created = now_iso()
    result_id = args.result_id or f'result_{timestamp()}__{slugify(Path(stored_path).stem)}'
    existing = [r for r in read_tsv(indexes_dir(root) / 'results.tsv') if r.get('result_id') == result_id]
    if existing:
        raise ProjectOSError(f'Result already exists: {result_id}')
    row = {
        'result_id': result_id,
        'branch_id': branch_id,
        'task_id': task_id,
        'run_id': args.run_id,
        'status': args.status,
        'type': args.type,
        'path': stored_path,
        'title': args.title or Path(stored_path).name,
        'created_at': created,
        'accepted_at': created if args.status in {'accepted', 'current', 'release'} else '',
        'promoted_to': '',
        'replaced_by': '',
        'notes': args.notes or '',
    }
    upsert_tsv(indexes_dir(root) / 'results.tsv', INDEX_HEADERS['results.tsv'], 'result_id', row)
    tdir = task_dir(root, task_id, branch_id=branch_id) if task_id else None
    if tdir:
        upsert_tsv(
            tdir / 'result_links.tsv',
            RESULT_LINK_HEADERS,
            'result_id',
            {
                'result_id': result_id,
                'branch_id': branch_id,
                'status': args.status,
                'path': stored_path,
                'run_id': args.run_id,
                'created_at': created,
                'notes': args.notes or '',
            },
        )
    outputs = manifest.setdefault('outputs', [])
    outputs.append({'result_id': result_id, 'path': stored_path, 'status': args.status, 'type': args.type, 'title': row['title']})
    manifest['result_status'] = args.status if args.status != 'draft' else manifest.get('result_status', 'draft')
    write_json(manifest_path, manifest)
    refresh_results_index_markdown(root)
    append_event(root, 'result.registered', branch_id=branch_id, task_id=task_id, run_id=args.run_id, result_id=result_id, detail={'path': stored_path, 'status': args.status})
    print_json({'registered_result': result_id, 'branch_id': branch_id, 'task_id': task_id, 'run_id': args.run_id, 'status': args.status, 'path': stored_path})
    return 0


def command_promote_result(args: Any) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    results_path = indexes_dir(root) / 'results.tsv'
    rows = read_tsv(results_path)
    matches = [r for r in rows if r.get('result_id') == args.result_id]
    if not matches:
        raise ProjectOSError(f'Missing result: {args.result_id}')
    row = matches[0]
    source_path, _ = project_relative_or_absolute(root, row['path'])
    dest_path, dest_stored = project_relative_or_absolute(root, args.to)
    if not dest_stored.startswith('current/'):
        raise ProjectOSError('Promotion target must be under current/')
    if not source_path.exists():
        raise ProjectOSError(f'Source result path does not exist: {source_path}')
    if dest_path.exists() and not args.replace:
        raise ProjectOSError(f'Destination exists; pass --replace to overwrite: {dest_path}')
    payload = {'result_id': args.result_id, 'source': relpath(root, source_path), 'destination': dest_stored, 'applied': bool(args.apply)}
    if not args.apply:
        print_json({'dry_run_promotion': payload})
        return 0
    if not getattr(args, 'approved', False):
        raise ProjectOSError('promote-result --apply requires --approved')
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_file():
        shutil.copy2(source_path, dest_path)
    else:
        if dest_path.exists():
            shutil.rmtree(dest_path)
        shutil.copytree(source_path, dest_path)
    promoted_at = now_iso()
    for existing in rows:
        if existing.get('result_id') == args.result_id:
            existing['status'] = 'current'
            existing['accepted_at'] = existing.get('accepted_at') or promoted_at
            prior = existing.get('promoted_to', '')
            existing['promoted_to'] = dest_stored if not prior else prior + ',' + dest_stored
            existing['notes'] = (existing.get('notes', '') + '; promoted to ' + dest_stored).strip('; ')
    write_tsv(results_path, INDEX_HEADERS['results.tsv'], rows)
    refresh_results_index_markdown(root)
    manifest_path = find_run_manifest(root, row.get('run_id', ''))
    if manifest_path:
        manifest = read_json(manifest_path)
        manifest.setdefault('promoted_to', []).append(dest_stored)
        manifest['result_status'] = 'current'
        write_json(manifest_path, manifest)
    append_event(root, 'result.promoted', branch_id=row.get('branch_id', ''), task_id=row.get('task_id', ''), run_id=row.get('run_id', ''), result_id=args.result_id, detail={'target': dest_stored})
    print_json({'promoted_result': payload})
    return 0


def command_list_results(args: Any) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    rows = read_tsv(indexes_dir(root) / 'results.tsv')
    if args.branch_id:
        rows = [r for r in rows if r.get('branch_id') == args.branch_id]
    if args.task_id:
        rows = [r for r in rows if r.get('task_id') == args.task_id]
    if args.status:
        rows = [r for r in rows if r.get('status') == args.status]
    print_json({'results': rows, 'count': len(rows)})
    return 0


def command_show_result(args: Any) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    rows = [r for r in read_tsv(indexes_dir(root) / 'results.tsv') if r.get('result_id') == args.result_id]
    if not rows:
        raise ProjectOSError(f'Missing result: {args.result_id}')
    row = rows[0]
    manifest_path = find_run_manifest(root, row.get('run_id', '')) if row.get('run_id') else None
    print_json({'result': row, 'source_run_manifest': relpath(root, manifest_path) if manifest_path else ''})
    return 0


def release_manifest_headers() -> list[str]:
    return ['result_id', 'branch_id', 'task_id', 'run_id', 'status', 'type', 'source_path', 'release_path', 'title', 'checksum']


def release_checksum_headers() -> list[str]:
    return ['sha256', 'path', 'bytes']


def select_release_results(root: Path, result_ids: list[str], allow_candidate: bool = False) -> list[dict[str, str]]:
    rows = read_tsv(indexes_dir(root) / 'results.tsv')
    if result_ids:
        selected: list[dict[str, str]] = []
        missing: list[str] = []
        for rid in result_ids:
            match = next((r for r in rows if r.get('result_id') == rid), None)
            if match:
                selected.append(match)
            else:
                missing.append(rid)
        if missing:
            raise ProjectOSError(f'Missing result(s): {", ".join(missing)}')
    else:
        selected = [r for r in rows if r.get('status') in {'current', 'accepted'}]
    allowed = {'current', 'accepted', 'release'} | ({'candidate'} if allow_candidate else set())
    bad = [r.get('result_id', '') for r in selected if r.get('status') not in allowed]
    if bad:
        raise ProjectOSError(f'Release can only include accepted/current results unless --allow-candidate is set: {", ".join(bad)}')
    if not selected:
        raise ProjectOSError('No release results selected; pass --result-id or accept/promote results first')
    return selected


def copy_result_to_release(root: Path, row: dict[str, str], artifacts_dir: Path, replace: bool) -> tuple[str, str]:
    source, _ = project_relative_or_absolute(root, row.get('path', ''))
    if not source.exists():
        raise ProjectOSError(f'Result path missing: {row.get("result_id")}: {row.get("path")}')
    safe_name = f"{slugify(row.get('result_id', 'result'), 80)}__{source.name}"
    dest = artifacts_dir / safe_name
    if dest.exists():
        if not replace:
            raise ProjectOSError(f'Release artifact exists; pass --replace: {relpath(root, dest)}')
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copy2(source, dest)
    else:
        shutil.copytree(source, dest)
    return relpath(root, dest), checksum_path(dest)


def collect_release_checksums(root: Path, release_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in sorted(p for p in release_dir.rglob('*') if p.is_file() and p.name != 'CHECKSUMS.tsv'):
        rows.append({'sha256': checksum_file(item), 'path': relpath(root, item), 'bytes': item.stat().st_size})
    return rows


def command_build_release(args: Any) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    if args.status not in RELEASE_STATUSES:
        raise ProjectOSError(f'Invalid release status: {args.status}')
    selected = select_release_results(root, args.result_id, allow_candidate=args.allow_candidate)
    release_id = args.release_id or f'release_{timestamp()}'
    release_dir = root / 'release' / release_id
    planned = [
        {
            'result_id': r.get('result_id', ''),
            'source': r.get('path', ''),
            'target': f"release/{release_id}/artifacts/{slugify(r.get('result_id','result'), 80)}__{Path(r.get('path','')).name}",
        }
        for r in selected
    ]
    if not args.apply:
        print_json({'dry_run_release': {'release_id': release_id, 'results': planned, 'path': relpath(root, release_dir), 'apply_required': True}})
        return 0
    if not getattr(args, 'approved', False):
        raise ProjectOSError('build-release --apply requires --approved')
    if release_dir.exists() and not args.replace:
        raise ProjectOSError(f'Release directory exists; pass --replace: {relpath(root, release_dir)}')
    release_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = release_dir / 'artifacts'
    manifest_rows: list[dict[str, Any]] = []
    for row in selected:
        release_path, checksum = copy_result_to_release(root, row, artifacts_dir, args.replace)
        manifest_rows.append(
            {
                'result_id': row.get('result_id', ''),
                'branch_id': row.get('branch_id', ''),
                'task_id': row.get('task_id', ''),
                'run_id': row.get('run_id', ''),
                'status': row.get('status', ''),
                'type': row.get('type', ''),
                'source_path': row.get('path', ''),
                'release_path': release_path,
                'title': row.get('title', ''),
                'checksum': checksum,
            }
        )
    write_tsv(release_dir / 'MANIFEST.tsv', release_manifest_headers(), manifest_rows)
    write_tsv(release_dir / 'CHECKSUMS.tsv', release_checksum_headers(), collect_release_checksums(root, release_dir))
    readme = ['# Release ' + release_id, '', f'Created: {now_iso()}', '', '## Included results', '']
    for row in manifest_rows:
        readme.append(f"- `{row['result_id']}` from `{row['source_path']}` -> `{row['release_path']}`")
    readme += ['', '## Files', '', '- `MANIFEST.tsv`: result-level provenance.', '- `CHECKSUMS.tsv`: per-file SHA-256 checksums.', '- `artifacts/`: copied release artifacts.', '']
    (release_dir / 'README.md').write_text('\n'.join(readme), encoding='utf-8')
    release_row = {
        'release_id': release_id,
        'status': args.status,
        'path': relpath(root, release_dir),
        'created_at': now_iso(),
        'source_branch_ids': ','.join(sorted({r.get('branch_id', '') for r in selected if r.get('branch_id')})),
        'source_result_ids': ','.join([r.get('result_id', '') for r in selected]),
        'notes': args.notes or '',
    }
    upsert_tsv(indexes_dir(root) / 'releases.tsv', INDEX_HEADERS['releases.tsv'], 'release_id', release_row)
    append_event(root, 'release.created', branch_id=current_branch(root), detail={'release_id': release_id, 'result_ids': release_row['source_result_ids'], 'path': relpath(root, release_dir)})
    print_json({'built_release': release_id, 'release': release_row, 'manifest_rows': len(manifest_rows)})
    return 0


def command_list_releases(args: Any) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    rows = read_tsv(indexes_dir(root) / 'releases.tsv')
    if args.status:
        rows = [r for r in rows if r.get('status') == args.status]
    print_json({'releases': rows, 'count': len(rows)})
    return 0


def command_show_release(args: Any) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    row = next((r for r in read_tsv(indexes_dir(root) / 'releases.tsv') if r.get('release_id') == args.release_id), None)
    if not row:
        raise ProjectOSError(f'Missing release: {args.release_id}')
    rdir = root / row.get('path', '')
    manifest = read_tsv(rdir / 'MANIFEST.tsv') if (rdir / 'MANIFEST.tsv').exists() else []
    checksums = read_tsv(rdir / 'CHECKSUMS.tsv') if (rdir / 'CHECKSUMS.tsv').exists() else []
    print_json({'release': row, 'manifest': manifest, 'checksums_count': len(checksums)})
    return 0


def command_validate_release(args: Any) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    releases = read_tsv(indexes_dir(root) / 'releases.tsv')
    row = next((r for r in releases if r.get('release_id') == args.release_id), None)
    if not row:
        raise ProjectOSError(f'Missing release: {args.release_id}')
    rdir = root / row.get('path', '')
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not rdir.exists():
        errors.append({'path': relpath(root, rdir), 'issue': 'missing release directory'})
    for name in ['README.md', 'MANIFEST.tsv', 'CHECKSUMS.tsv']:
        if not (rdir / name).exists():
            errors.append({'path': relpath(root, rdir / name), 'issue': 'missing release file'})
    if (rdir / 'MANIFEST.tsv').exists():
        first = (rdir / 'MANIFEST.tsv').read_text(encoding='utf-8', errors='replace').splitlines()[:1]
        if not first or first[0].split('\t') != release_manifest_headers():
            errors.append({'path': relpath(root, rdir / 'MANIFEST.tsv'), 'issue': 'manifest header mismatch'})
        for item in read_tsv(rdir / 'MANIFEST.tsv'):
            target = root / item.get('release_path', '')
            if not target.exists():
                errors.append({'path': item.get('release_path', ''), 'issue': 'release artifact missing'})
            elif item.get('checksum') and checksum_path(target) != item.get('checksum'):
                errors.append({'path': item.get('release_path', ''), 'issue': 'aggregate checksum mismatch'})
    if (rdir / 'CHECKSUMS.tsv').exists():
        first = (rdir / 'CHECKSUMS.tsv').read_text(encoding='utf-8', errors='replace').splitlines()[:1]
        if not first or first[0].split('\t') != release_checksum_headers():
            errors.append({'path': relpath(root, rdir / 'CHECKSUMS.tsv'), 'issue': 'checksums header mismatch'})
        for item in read_tsv(rdir / 'CHECKSUMS.tsv'):
            target = root / item.get('path', '')
            if item.get('path', '').endswith('CHECKSUMS.tsv'):
                continue
            if not target.exists():
                errors.append({'path': item.get('path', ''), 'issue': 'checksum target missing'})
            elif checksum_file(target) != item.get('sha256'):
                errors.append({'path': item.get('path', ''), 'issue': 'file checksum mismatch'})
    if args.record and not errors:
        for rel in releases:
            if rel.get('release_id') == args.release_id:
                rel['status'] = 'validated'
        write_tsv(indexes_dir(root) / 'releases.tsv', INDEX_HEADERS['releases.tsv'], releases)
        append_event(root, 'release.validated', branch_id=current_branch(root), detail={'release_id': args.release_id})
    payload = {'release_id': args.release_id, 'valid': not errors, 'errors': len(errors), 'warnings': len(warnings), 'error_items': errors, 'warning_items': warnings, 'recorded': bool(args.record and not errors)}
    print_json(payload)
    return 1 if errors else 0


def update_result_row(root: Path, result_id: str, updater: Any) -> dict[str, str]:
    path = indexes_dir(root) / 'results.tsv'
    rows = read_tsv(path)
    updated: dict[str, str] | None = None
    for row in rows:
        if row.get('result_id') == result_id:
            updater(row)
            updated = row
    if not updated:
        raise ProjectOSError(f'Missing result: {result_id}')
    write_tsv(path, INDEX_HEADERS['results.tsv'], rows)
    refresh_results_index_markdown(root)
    return updated


def command_accept_result(args: Any) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    if not args.approved:
        raise ProjectOSError('accept-result requires --approved')
    accepted_at = now_iso()

    def updater(row: dict[str, str]) -> None:
        row['status'] = 'accepted'
        row['accepted_at'] = row.get('accepted_at') or accepted_at
        if args.notes:
            row['notes'] = (row.get('notes', '') + '; ' + args.notes).strip('; ')

    row = update_result_row(root, args.result_id, updater)
    manifest_path = find_run_manifest(root, row.get('run_id', ''))
    if manifest_path:
        manifest = read_json(manifest_path)
        manifest['result_status'] = 'accepted'
        for output in manifest.get('outputs', []) if isinstance(manifest.get('outputs', []), list) else []:
            if isinstance(output, dict) and output.get('result_id') == args.result_id:
                output['status'] = 'accepted'
        write_json(manifest_path, manifest)
    append_event(root, 'result.accepted', branch_id=row.get('branch_id', ''), task_id=row.get('task_id', ''), run_id=row.get('run_id', ''), result_id=args.result_id, detail={'notes': args.notes or ''})
    print_json({'accepted_result': args.result_id, 'result': row})
    return 0


def command_supersede_result(args: Any) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    if not args.approved:
        raise ProjectOSError('supersede-result requires --approved')
    if args.replaced_by == args.result_id:
        raise ProjectOSError('A result cannot supersede itself')
    if args.replaced_by and not any(r.get('result_id') == args.replaced_by for r in read_tsv(indexes_dir(root) / 'results.tsv')):
        raise ProjectOSError(f'Replacement result not found: {args.replaced_by}')

    def updater(row: dict[str, str]) -> None:
        row['status'] = 'superseded'
        row['replaced_by'] = args.replaced_by or row.get('replaced_by', '')
        if args.notes:
            row['notes'] = (row.get('notes', '') + '; ' + args.notes).strip('; ')

    row = update_result_row(root, args.result_id, updater)
    append_event(root, 'result.superseded', branch_id=row.get('branch_id', ''), task_id=row.get('task_id', ''), run_id=row.get('run_id', ''), result_id=args.result_id, detail={'replaced_by': args.replaced_by or '', 'notes': args.notes or ''})
    print_json({'superseded_result': args.result_id, 'result': row})
    return 0


def command_show_current(args: Any) -> int:
    root = Path(args.root).resolve()
    ensure_initialized(root)
    rows = read_tsv(indexes_dir(root) / 'results.tsv')
    views = current_result_views(root, rows)
    scope = getattr(args, 'scope', 'all') or 'all'
    branch_id = getattr(args, 'branch_id', '') or ''
    if getattr(args, 'project_only', False):
        scope = 'project'
    if branch_id:
        scope = 'branch'
    if scope == 'project':
        payload: dict[str, Any] = {
            'scope': 'project',
            'current_results': views['project']['results'],
            'count': views['project']['count'],
        }
    elif scope == 'branch':
        branch_id = branch_id or current_branch(root)
        bucket = views['branches'].get(branch_id, {'count': 0, 'results': []})
        payload = {
            'scope': 'branch',
            'branch_id': branch_id,
            'current_results': bucket['results'],
            'count': bucket['count'],
        }
    else:
        payload = {
            'scope': 'all',
            'current_results': views['all']['results'],
            'count': views['all']['count'],
            'project': views['project'],
            'branches': views['branches'],
        }
    if getattr(args, 'audit', False):
        payload['promotion_audit'] = promotion_audit(root, rows)
    print_json(payload)
    return 0
