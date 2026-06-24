from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Any

from _schema import *
from _paths import *
from _project_io import *
from _views import refresh_data_assets_markdown


DEFAULT_EXTERNALIZE_REPORT_DIR = '.project_os/exports/asset_externalization'
IGNORED_SCAN_DIR_NAMES = {'.git', '.project_os', '__pycache__', '.venv', 'venv', '.pytest_cache', '.mypy_cache'}
TEXT_REFERENCE_SUFFIXES = {'.md', '.txt', '.py', '.sh', '.yaml', '.yml', '.json', '.jsonl', '.tsv', '.toml', '.ini', '.cfg'}


def ensure_initialized(root: Path) -> None:
    if not (project_os(root) / 'workflow.md').exists():
        raise ProjectOSError(f'Missing {OS_DIR}/workflow.md. Run init first.')


def current_branch(root: Path) -> str:
    return current_pointer(root, 'current_branch') or DEFAULT_BRANCH


def looks_like_url(raw: str) -> bool:
    return bool(re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', raw or ''))


def checksum_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_path(path: Path) -> str:
    """Return a deterministic sha256 for a file or directory.

    Directory checksums include relative file paths plus file bytes so a renamed
    file changes the digest. This is intentionally simple and portable; release
    packages also write per-file checksums separately.
    """
    if path.is_file():
        return checksum_file(path)
    if path.is_dir():
        digest = hashlib.sha256()
        for item in sorted(p for p in path.rglob('*') if p.is_file()):
            rel = item.relative_to(path).as_posix()
            digest.update(rel.encode('utf-8') + b'\0')
            digest.update(checksum_file(item).encode('ascii') + b'\0')
        return digest.hexdigest()
    raise ProjectOSError(f'Cannot checksum missing path: {path}')


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {'true', 'false'}:
        return lowered == 'true'
    if lowered in {'null', 'none'}:
        return None
    return value.strip("'\"")


def parse_external_assets_config(root: Path) -> dict[str, Any]:
    path = project_os(root) / 'config.yaml'
    config: dict[str, Any] = {
        'path': relpath(root, path),
        'exists': path.exists(),
        'roots': [],
        'default_primary_root': '',
        'default_backup_root': '',
        'default_mode': 'copy',
        'allow_optional_symlink_compat': False,
    }
    if not path.exists():
        return config

    in_section = False
    current_list = ''
    for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if re.match(r'^external_assets:\s*$', raw):
            in_section = True
            current_list = ''
            continue
        if not in_section:
            continue
        if raw and not raw.startswith(' '):
            break
        stripped = raw.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('- ') and current_list == 'roots':
            config['roots'].append(stripped[2:].strip().strip("'\""))
            continue
        match = re.match(r'^([A-Za-z0-9_]+):\s*(.*)$', stripped)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key == 'roots':
            current_list = 'roots'
            continue
        current_list = ''
        config[key] = parse_scalar(value)
    return config


def normalize_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def merge_storage_roots(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            value = str(raw or '').strip()
            if not value:
                continue
            normalized = normalize_path(Path(value)).as_posix()
            if normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return merged


def storage_root_for_path(path: Path, roots: list[str]) -> str:
    target = normalize_path(path)
    for raw in roots:
        if not raw:
            continue
        candidate = normalize_path(Path(raw))
        try:
            target.relative_to(candidate)
            return candidate.as_posix()
        except ValueError:
            continue
    return ''


def size_bytes_for_path(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob('*') if item.is_file())
    return 0


def asset_rows(root: Path) -> list[dict[str, str]]:
    return read_tsv(indexes_dir(root) / 'assets.tsv')


def asset_location_rows(root: Path) -> list[dict[str, str]]:
    return read_tsv(indexes_dir(root) / 'asset_locations.tsv')


def find_asset_row(root: Path, asset_id: str) -> dict[str, str] | None:
    for row in asset_rows(root):
        if row.get('asset_id') == asset_id:
            return row
    return None


def find_asset_row_by_path(root: Path, target: Path) -> dict[str, str] | None:
    wanted = normalize_path(target).as_posix()
    for row in asset_rows(root):
        path = asset_path_from_row(root, row)
        if path and normalize_path(path).as_posix() == wanted:
            return row
    return None


def asset_locations_for_asset(root: Path, asset_id: str) -> list[dict[str, str]]:
    return [row for row in asset_location_rows(root) if row.get('asset_id') == asset_id]


def asset_path_from_row(root: Path, row: dict[str, str]) -> Path | None:
    raw = row.get('path', '')
    if not raw or looks_like_url(raw):
        return None
    path, _ = project_relative_or_absolute(root, raw)
    return path


def asset_location_path(root: Path, row: dict[str, str]) -> Path | None:
    raw = row.get('path', '')
    if not raw or looks_like_url(raw):
        return None
    path, _ = project_relative_or_absolute(root, raw)
    return path


def build_location_id(asset_id: str, role: str, path: Path, storage_root: str = '') -> str:
    if role == 'primary':
        return f'{asset_id}__primary'
    seed = storage_root or path.parent.as_posix() or path.as_posix()
    return f'{asset_id}__{role}__{slugify(seed, max_len=32)}'


def build_precise_location_id(asset_id: str, role: str, path: Path) -> str:
    if role == 'primary':
        return f'{asset_id}__primary'
    digest = hashlib.sha1(normalize_path(path).as_posix().encode('utf-8')).hexdigest()[:10]
    return f'{asset_id}__{role}__{digest}'


def upsert_asset_location(root: Path, row: dict[str, Any]) -> None:
    upsert_tsv(indexes_dir(root) / 'asset_locations.tsv', INDEX_HEADERS['asset_locations.tsv'], 'location_id', row)


def primary_location_row_for_asset(root: Path, row: dict[str, str], *, notes: str = 'Derived from assets.tsv primary path.') -> dict[str, Any] | None:
    target = asset_path_from_row(root, row)
    if not target:
        return None
    existing = next((item for item in asset_locations_for_asset(root, row.get('asset_id', '')) if item.get('location_id') == f"{row.get('asset_id', '')}__primary"), None)
    path_value = row.get('path', '')
    exists = target.exists()
    config = parse_external_assets_config(root)
    configured_roots = [str(item) for item in config.get('roots', []) if str(item)]
    storage_root = storage_root_for_path(target, merge_storage_roots(configured_roots, [existing.get('storage_root', '')] if existing else []))
    location_status = 'available' if exists else 'missing'
    registered_at = (existing or {}).get('registered_at', '') or row.get('registered_at', '') or now_iso()
    last_checked_at = (existing or {}).get('last_checked_at', '')
    if exists and not last_checked_at:
        last_checked_at = now_iso()
    resolved_notes = notes
    if existing and existing.get('notes') and notes == 'Derived from assets.tsv primary path.':
        resolved_notes = existing.get('notes', '')
    return {
        'asset_id': row.get('asset_id', ''),
        'location_id': f"{row.get('asset_id', '')}__primary",
        'role': 'primary',
        'path': path_value,
        'storage_root': storage_root,
        'status': location_status,
        'size_bytes': str(size_bytes_for_path(target)) if exists else '',
        'checksum': row.get('checksum', ''),
        'registered_at': registered_at,
        'last_checked_at': last_checked_at,
        'notes': resolved_notes,
    }


def sync_primary_locations_from_assets(root: Path) -> None:
    for row in asset_rows(root):
        primary = primary_location_row_for_asset(root, row)
        if primary:
            upsert_asset_location(root, primary)


def asset_usage_row(asset_id: str, branch_id: str = '', task_id: str = '', run_id: str = '', result_id: str = '', usage_kind: str = 'input', notes: str = '') -> dict[str, Any]:
    return {'asset_id': asset_id, 'branch_id': branch_id, 'task_id': task_id, 'run_id': run_id, 'result_id': result_id, 'usage_kind': usage_kind, 'registered_at': now_iso(), 'notes': notes}


def refresh_asset_usage(root: Path) -> None:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for run_base in [root / 'runs', root / 'analysis_runs']:
        if not run_base.exists():
            continue
        for manifest_file in sorted(run_base.glob('*/*/RUN_MANIFEST.json')):
            manifest = read_json(manifest_file)
            branch_id = str(manifest.get('branch_id') or manifest_file.parent.parent.name)
            task_id = str(manifest.get('task_id') or '')
            run_id = str(manifest.get('run_id') or manifest_file.parent.name)
            for collection, default_kind in [('inputs', 'input'), ('outputs', 'output')]:
                for item in manifest.get(collection, []) if isinstance(manifest.get(collection, []), list) else []:
                    if not isinstance(item, dict) or not item.get('asset_id'):
                        continue
                    result_id = str(item.get('result_id') or '')
                    usage_kind = str(item.get('usage_kind') or item.get('role') or default_kind)
                    key = (str(item['asset_id']), branch_id, task_id, run_id, result_id, usage_kind)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({'asset_id': item['asset_id'], 'branch_id': branch_id, 'task_id': task_id, 'run_id': run_id, 'result_id': result_id, 'usage_kind': usage_kind, 'registered_at': str(item.get('registered_at') or manifest.get('created_at') or ''), 'notes': str(item.get('notes') or '')})
    write_tsv(indexes_dir(root) / 'asset_usage.tsv', INDEX_HEADERS['asset_usage.tsv'], rows)


def upsert_asset_usage(root: Path, row: dict[str, Any]) -> None:
    path = indexes_dir(root) / 'asset_usage.tsv'
    rows = read_tsv(path)
    key_fields = ['asset_id', 'branch_id', 'task_id', 'run_id', 'result_id', 'usage_kind']
    key = tuple(str(row.get(k, '')) for k in key_fields)
    updated: list[dict[str, Any]] = []
    replaced = False
    for existing in rows:
        if tuple(existing.get(k, '') for k in key_fields) == key:
            updated.append({h: row.get(h, existing.get(h, '')) for h in INDEX_HEADERS['asset_usage.tsv']})
            replaced = True
        else:
            updated.append(existing)
    if not replaced:
        updated.append({h: row.get(h, '') for h in INDEX_HEADERS['asset_usage.tsv']})
    write_tsv(path, INDEX_HEADERS['asset_usage.tsv'], updated)


def parse_size_bytes(raw: str) -> int:
    value = str(raw or '').strip()
    if not value:
        raise ProjectOSError('Missing size threshold')
    match = re.fullmatch(r'(?i)(\d+(?:\.\d+)?)\s*([kmgtp]?)(?:i?b)?', value)
    if not match:
        raise ProjectOSError(f'Invalid size threshold: {raw}')
    number = float(match.group(1))
    suffix = match.group(2).upper()
    multipliers = {'': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4, 'P': 1024**5}
    return int(number * multipliers[suffix])


def iter_project_paths(root: Path, *, max_depth: int = 0) -> list[Path]:
    collected: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        try:
            rel = current.relative_to(root)
            depth = len(rel.parts)
        except ValueError:
            depth = 0
        dirnames[:] = [name for name in dirnames if name not in IGNORED_SCAN_DIR_NAMES]
        if max_depth and depth >= max_depth:
            dirnames[:] = []
        for name in filenames:
            collected.append(current / name)
        for name in dirnames:
            candidate = current / name
            if candidate.is_symlink():
                collected.append(candidate)
    return collected


def scan_large_files(root: Path, threshold_bytes: int, *, max_files: int = 0, max_depth: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in iter_project_paths(root, max_depth=max_depth):
        if path.is_symlink() or not path.exists() or not path.is_file():
            continue
        size = path.stat().st_size
        if size < threshold_bytes:
            continue
        asset_row = find_asset_row_by_path(root, path)
        rows.append({
            'path': relpath(root, path),
            'absolute_path': path.as_posix(),
            'size_bytes': size,
            'registered_asset_id': asset_row.get('asset_id', '') if asset_row else '',
        })
        if max_files and len(rows) >= max_files:
            break
    return sorted(rows, key=lambda item: (int(item.get('size_bytes', 0)), str(item.get('path', ''))), reverse=True)


def scan_broken_symlinks(root: Path, *, max_files: int = 0, max_depth: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in iter_project_paths(root, max_depth=max_depth):
        if not path.is_symlink() or path.exists():
            continue
        rows.append({
            'path': relpath(root, path),
            'absolute_path': path.as_posix(),
            'link_target': os.readlink(path),
        })
        if max_files and len(rows) >= max_files:
            break
    return rows


def structured_path_references(root: Path, source_path: Path) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    abs_path = normalize_path(source_path).as_posix()
    rel_path = relpath(root, source_path)
    source_abs = source_path.expanduser()
    if not source_abs.is_absolute():
        source_abs = root / source_abs
    candidates = {abs_path, rel_path, f'./{rel_path}', source_abs.as_posix()}
    try:
        lexical_rel = source_abs.relative_to(root.resolve()).as_posix()
    except ValueError:
        lexical_rel = ''
    if lexical_rel:
        candidates.add(lexical_rel)
        candidates.add(f'./{lexical_rel}')

    for manifest_file in sorted((root / 'runs').glob('*/*/RUN_MANIFEST.json')) + sorted((root / 'analysis_runs').glob('*/*/RUN_MANIFEST.json')):
        manifest = read_json(manifest_file)
        for field in ['inputs', 'outputs']:
            for item in manifest.get(field, []) if isinstance(manifest.get(field, []), list) else []:
                if not isinstance(item, dict):
                    continue
                raw = str(item.get('path', '') or '')
                if raw and raw in candidates:
                    refs.append({'kind': 'run_manifest', 'file': relpath(root, manifest_file), 'field': field, 'run_id': str(manifest.get('run_id', '')), 'path': raw})
    for manifest_file in sorted((project_os(root) / 'branches').glob('*/tasks/*/context_manifest.jsonl')):
        for idx, item in enumerate(read_jsonl(manifest_file), start=1):
            if not isinstance(item, dict):
                continue
            raw = str(item.get('path', '') or '')
            if raw and raw in candidates:
                refs.append({'kind': 'context_manifest', 'file': relpath(root, manifest_file), 'line': str(idx), 'path': raw})
    return refs


def text_path_references(root: Path, source_path: Path, *, max_hits: int = 50) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    abs_path = normalize_path(source_path).as_posix()
    rel_value = relpath(root, source_path)
    source_abs = source_path.expanduser()
    if not source_abs.is_absolute():
        source_abs = root / source_abs
    search_terms = [abs_path, rel_value, f'./{rel_value}', source_abs.as_posix()]
    try:
        lexical_rel = source_abs.relative_to(root.resolve()).as_posix()
    except ValueError:
        lexical_rel = ''
    if lexical_rel:
        search_terms.extend([lexical_rel, f'./{lexical_rel}'])
    for path in iter_project_paths(root):
        if path.suffix.lower() not in TEXT_REFERENCE_SUFFIXES:
            continue
        if not path.exists() or not path.is_file():
            continue
        try:
            if path.stat().st_size > 1024 * 1024:
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for term in search_terms:
            if term and term in text:
                hits.append({'kind': 'text', 'file': relpath(root, path), 'matched': term})
                break
        if len(hits) >= max_hits:
            break
    return hits


def resolve_external_roots(root: Path, primary_root: str = '', backup_root: str = '') -> dict[str, Any]:
    config = parse_external_assets_config(root)
    configured = [str(item) for item in config.get('roots', []) if str(item)]
    primary = primary_root or str(config.get('default_primary_root') or '') or (configured[0] if configured else '')
    backup = backup_root or str(config.get('default_backup_root') or '')
    if not backup and len(configured) > 1:
        backup = configured[1]
    return {
        'config': config,
        'roots': configured,
        'primary_root': primary,
        'backup_root': backup,
        'effective_roots': merge_storage_roots(configured, [primary, backup]),
        'default_mode': str(config.get('default_mode') or 'copy'),
    }


def path_within_root(path: Path, root: Path) -> bool:
    target = normalize_path(path)
    project_root = normalize_path(root)
    try:
        target.relative_to(project_root)
        return True
    except ValueError:
        return False


def resolve_cli_path(root: Path, raw: str, *, preserve_relative: bool = True) -> tuple[Path, str]:
    value = str(raw or '').strip()
    if not value:
        raise ProjectOSError('Missing path value')
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        resolved = normalize_path(candidate)
        return resolved, relpath(root, resolved)
    resolved = normalize_path(root / candidate)
    return resolved, candidate.as_posix() if preserve_relative else relpath(root, resolved)


def default_asset_id_for_path(root: Path, target: Path) -> str:
    base = slugify(target.stem or target.name)
    candidate = f'asset_{base}'
    row = find_asset_row(root, candidate)
    if not row:
        return candidate
    existing_path = asset_path_from_row(root, row)
    if existing_path and normalize_path(existing_path).as_posix() == normalize_path(target).as_posix():
        return candidate
    return f'asset_{timestamp()}__{base}'


def suggested_external_subpath(root: Path, source_path: Path, asset_id: str) -> str:
    resolved = normalize_path(source_path)
    root_resolved = normalize_path(root)
    try:
        rel = resolved.relative_to(root_resolved)
        return Path(root.name) / rel
    except ValueError:
        return Path(root.name) / 'externalized' / asset_id / source_path.name


def write_asset_report(root: Path, output: str, prefix: str, payload: dict[str, Any]) -> str:
    out = Path(output).expanduser()
    if not out.is_absolute():
        out = root / out
    out.mkdir(parents=True, exist_ok=True)
    report = out / f'{prefix}_{timestamp()}.json'
    write_json(report, payload)
    return relpath(root, report)


def storage_root_status(path_value: str) -> dict[str, Any]:
    if not path_value:
        return {'path': '', 'exists': False, 'mounted': False, 'free_bytes': 0, 'total_bytes': 0}
    path = normalize_path(Path(path_value))
    exists = path.exists()
    mounted = path.is_dir()
    free_bytes = 0
    total_bytes = 0
    try:
        usage = shutil.disk_usage(path if path.exists() else path.parent)
        free_bytes = usage.free
        total_bytes = usage.total
    except OSError:
        pass
    return {'path': path.as_posix(), 'exists': exists, 'mounted': mounted, 'free_bytes': free_bytes, 'total_bytes': total_bytes}


def copy_path(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def ensure_safe_destination(src: Path, dst: Path) -> None:
    src_norm = normalize_path(src)
    dst_norm = normalize_path(dst)
    if src_norm == dst_norm:
        return
    try:
        dst_norm.relative_to(src_norm)
        raise ProjectOSError(f'Destination cannot be nested inside source: {dst}')
    except ValueError:
        pass


def update_asset_row(root: Path, row: dict[str, Any]) -> None:
    upsert_tsv(indexes_dir(root) / 'assets.tsv', INDEX_HEADERS['assets.tsv'], 'asset_id', row)


def externalize_target_paths(root: Path, source_path: Path, asset_id: str, primary_root: str, backup_root: str = '', dest_subpath: str = '') -> dict[str, Path]:
    subpath = Path(dest_subpath) if dest_subpath else suggested_external_subpath(root, source_path, asset_id)
    primary = normalize_path(Path(primary_root) / subpath)
    result = {'primary': primary}
    if backup_root:
        result['backup'] = normalize_path(Path(backup_root) / subpath)
    return result


def build_externalization_preview(
    root: Path,
    source_path: Path,
    *,
    asset_id: str,
    primary_root: str,
    backup_root: str = '',
    dest_subpath: str = '',
    mode: str = 'copy',
) -> dict[str, Any]:
    targets = externalize_target_paths(root, source_path, asset_id, primary_root, backup_root, dest_subpath)
    source_checksum = checksum_path(source_path)
    source_size = size_bytes_for_path(source_path)
    refs = structured_path_references(root, source_path)
    text_refs = text_path_references(root, source_path)
    preview_targets: list[dict[str, Any]] = []
    for role, target in [('primary', targets['primary']), ('backup', targets.get('backup'))]:
        if not target:
            continue
        ensure_safe_destination(source_path, target)
        exists = target.exists()
        checksum_matches = False
        existing_checksum = ''
        if exists:
            try:
                existing_checksum = checksum_path(target)
                checksum_matches = existing_checksum == source_checksum
            except ProjectOSError:
                existing_checksum = ''
        preview_targets.append({
            'role': role,
            'path': target.as_posix(),
            'exists': exists,
            'existing_checksum': existing_checksum,
            'checksum_matches_source': checksum_matches,
            'storage_root': storage_root_for_path(target, [primary_root, backup_root]),
        })
    return {
        'asset_id': asset_id,
        'source': {
            'path': source_path.as_posix(),
            'project_relative_path': relpath(root, source_path),
            'size_bytes': source_size,
            'checksum': source_checksum,
            'inside_project_root': source_path.as_posix().startswith(normalize_path(root).as_posix() + '/'),
        },
        'mode': mode,
        'targets': preview_targets,
        'structured_references': refs,
        'text_references': text_refs,
        'reference_summary': {'structured_count': len(refs), 'text_count': len(text_refs)},
        'policy': 'externalize-asset uses copy/move + checksum verify + asset/location registration. Hard links are forbidden; symlinks are not canonical.',
    }


def build_location_preview(
    root: Path,
    raw_path: str,
    *,
    role: str,
    primary_checksum: str,
    storage_roots: list[str],
    preserve_relative: bool = True,
) -> dict[str, Any]:
    resolved, stored = resolve_cli_path(root, raw_path, preserve_relative=preserve_relative)
    lexical = Path(raw_path).expanduser()
    lexical_abs = lexical if lexical.is_absolute() else (root / lexical)
    exists = resolved.exists()
    entry_exists = os.path.lexists(lexical_abs)
    checksum = ''
    checksum_matches_primary = None
    status = 'missing'
    if exists:
        checksum = checksum_path(resolved)
        checksum_matches_primary = checksum == primary_checksum
        status = 'available' if checksum_matches_primary else 'stale_checksum'
    return {
        'role': role,
        'raw_path': raw_path,
        'path': stored,
        'absolute_path': resolved.as_posix(),
        'storage_root': storage_root_for_path(resolved, storage_roots),
        'exists': exists,
        'entry_exists': entry_exists,
        'is_symlink': lexical_abs.is_symlink(),
        'inside_project_root': not Path(stored).is_absolute(),
        'size_bytes': size_bytes_for_path(resolved) if exists else 0,
        'checksum': checksum,
        'checksum_matches_primary': checksum_matches_primary,
        'status': status,
    }


def asset_location_row_from_preview(
    root: Path,
    asset_id: str,
    preview: dict[str, Any],
    *,
    asset_checksum: str,
    notes: str,
    registered_at: str,
) -> dict[str, Any]:
    resolved = normalize_path(Path(str(preview.get('absolute_path', ''))))
    exists = bool(preview.get('exists', False))
    role = str(preview.get('role', ''))
    stored_path = str(preview.get('path', ''))
    existing_row = next(
        (
            item for item in asset_locations_for_asset(root, asset_id)
            if item.get('role') == role
            and item.get('path', '') == stored_path
        ),
        None,
    )
    return {
        'asset_id': asset_id,
        'location_id': (existing_row or {}).get('location_id', '') or build_precise_location_id(asset_id, role, Path(stored_path or resolved.as_posix())),
        'role': role,
        'path': stored_path,
        'storage_root': str(preview.get('storage_root', '')),
        'status': str(preview.get('status', 'missing')),
        'size_bytes': str(preview.get('size_bytes', 0)) if exists else '',
        'checksum': asset_checksum,
        'registered_at': registered_at,
        'last_checked_at': now_iso() if exists else '',
        'notes': notes,
    }


def create_or_update_asset_for_externalization(
    root: Path,
    *,
    existing_row: dict[str, str] | None,
    asset_id: str,
    kind: str,
    primary_path: str,
    checksum: str,
    notes: str,
    source_note: str = '',
    status: str = 'active',
) -> tuple[str, dict[str, Any], bool]:
    created_at = now_iso()
    if existing_row:
        row = dict(existing_row)
        row['path'] = primary_path
        row['kind'] = kind or row.get('kind', 'data')
        row['status'] = status or row.get('status', 'active')
        row['checksum'] = checksum or row.get('checksum', '')
        row['notes'] = notes or row.get('notes', '')
        if source_note:
            row['source_note'] = source_note
        update_asset_row(root, row)
        return existing_row.get('asset_id', asset_id), row, False
    row = {
        'asset_id': asset_id,
        'kind': kind or 'data',
        'path': primary_path,
        'version': '',
        'source_url': '',
        'source_note': source_note,
        'immutable': 'true' if (kind or 'data').lower() in {'raw', 'reference', 'data', 'dataset', 'input'} else 'false',
        'status': status,
        'registered_at': created_at,
        'checksum': checksum,
        'notes': notes,
    }
    update_asset_row(root, row)
    return asset_id, row, True


def register_externalization_locations(
    root: Path,
    *,
    asset_row: dict[str, Any],
    primary_target: Path,
    backup_target: Path | None,
    source_path: Path,
    source_checksum: str,
    mode: str,
    storage_roots: list[str] | None = None,
) -> list[dict[str, Any]]:
    roots = resolve_external_roots(root)
    effective_roots = merge_storage_roots(roots.get('effective_roots', []), storage_roots or [])
    registered: list[dict[str, Any]] = []

    primary_row = {
        'asset_id': asset_row.get('asset_id', ''),
        'location_id': build_location_id(asset_row.get('asset_id', ''), 'primary', primary_target, storage_root_for_path(primary_target, effective_roots)),
        'role': 'primary',
        'path': primary_target.as_posix(),
        'storage_root': storage_root_for_path(primary_target, effective_roots),
        'status': 'available' if primary_target.exists() else 'missing',
        'size_bytes': str(size_bytes_for_path(primary_target)) if primary_target.exists() else '',
        'checksum': source_checksum,
        'registered_at': asset_row.get('registered_at', '') or now_iso(),
        'last_checked_at': now_iso() if primary_target.exists() else '',
        'notes': f'Canonical primary location registered by externalize-asset ({mode}).',
    }
    upsert_asset_location(root, primary_row)
    registered.append(primary_row)

    if backup_target:
        backup_row = {
            'asset_id': asset_row.get('asset_id', ''),
            'location_id': build_location_id(asset_row.get('asset_id', ''), 'backup', backup_target, storage_root_for_path(backup_target, effective_roots)),
            'role': 'backup',
            'path': backup_target.as_posix(),
            'storage_root': storage_root_for_path(backup_target, effective_roots),
            'status': 'available' if backup_target.exists() else 'missing',
            'size_bytes': str(size_bytes_for_path(backup_target)) if backup_target.exists() else '',
            'checksum': source_checksum,
            'registered_at': now_iso(),
            'last_checked_at': now_iso() if backup_target.exists() else '',
            'notes': f'Backup location registered by externalize-asset ({mode}).',
        }
        upsert_asset_location(root, backup_row)
        registered.append(backup_row)

    source_role = 'mirror' if mode == 'copy' and source_path.exists() else 'unavailable'
    source_status = 'available' if mode == 'copy' and source_path.exists() else 'missing'
    source_exists = source_path.exists()
    source_row = {
        'asset_id': asset_row.get('asset_id', ''),
        'location_id': build_location_id(asset_row.get('asset_id', ''), source_role, source_path),
        'role': source_role,
        'path': source_path.as_posix(),
        'storage_root': storage_root_for_path(source_path, effective_roots),
        'status': source_status,
        'size_bytes': str(size_bytes_for_path(source_path)) if source_exists else '',
        'checksum': source_checksum,
        'registered_at': now_iso(),
        'last_checked_at': now_iso() if source_exists else '',
        'notes': 'Old path mapping retained for portability/audit; canonical recovery resolves via asset_id + asset_locations.tsv.',
    }
    upsert_asset_location(root, source_row)
    registered.append(source_row)
    return registered


def command_list_asset_locations(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    rows = asset_location_rows(root)
    if getattr(args, 'asset_id', ''):
        rows = [row for row in rows if row.get('asset_id') == args.asset_id]
    if getattr(args, 'role', ''):
        rows = [row for row in rows if row.get('role') == args.role]
    if getattr(args, 'status', ''):
        rows = [row for row in rows if row.get('status') == args.status]
    print_json({'asset_locations': rows, 'count': len(rows)}); return 0


def command_verify_external_assets(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    rows = asset_location_rows(root)
    if getattr(args, 'asset_id', ''):
        rows = [row for row in rows if row.get('asset_id') == args.asset_id]
    assets = {row.get('asset_id', ''): row for row in asset_rows(root)}
    checked_at = now_iso()
    results: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for row in rows:
        asset_id = row.get('asset_id', '')
        asset = assets.get(asset_id, {})
        target = asset_location_path(root, row)
        exists = bool(target and target.exists())
        current_checksum = ''
        checksum_matches = None
        if exists and getattr(args, 'checksum', False):
            current_checksum = checksum_path(target)
            expected = row.get('checksum') or asset.get('checksum', '')
            checksum_matches = (current_checksum == expected) if expected else True
        result = {
            'asset_id': asset_id,
            'location_id': row.get('location_id', ''),
            'role': row.get('role', ''),
            'status': row.get('status', ''),
            'path': row.get('path', ''),
            'storage_root': row.get('storage_root', ''),
            'exists': exists,
            'registered_checksum': row.get('checksum', '') or asset.get('checksum', ''),
            'current_checksum': current_checksum,
            'checksum_matches': checksum_matches,
        }
        results.append(result)
        if row.get('asset_id') not in assets:
            warnings.append({'location_id': row.get('location_id', ''), 'issue': f'missing asset row for {asset_id}'})
        if row.get('role') not in ASSET_LOCATION_ROLES:
            warnings.append({'location_id': row.get('location_id', ''), 'issue': f'nonstandard asset location role: {row.get("role")}'})
        if row.get('status') not in ASSET_LOCATION_STATUSES:
            warnings.append({'location_id': row.get('location_id', ''), 'issue': f'nonstandard asset location status: {row.get("status")}'})
        if not exists and row.get('status') == 'available':
            warnings.append({'location_id': row.get('location_id', ''), 'issue': 'location marked available but path is missing'})
        if checksum_matches is False:
            warnings.append({'location_id': row.get('location_id', ''), 'issue': 'location checksum mismatch'})

    role_counts: dict[str, int] = {}
    for row in results:
        role = str(row.get('role', '') or '(blank)')
        role_counts[role] = role_counts.get(role, 0) + 1

    print_json({
        'checked_at': checked_at,
        'asset_id': getattr(args, 'asset_id', ''),
        'locations_checked': len(results),
        'role_counts': role_counts,
        'checksum_checked': bool(getattr(args, 'checksum', False)),
        'results': results,
        'warnings': warnings,
        'ok': not warnings,
        'policy': 'verify-external-assets is read-only. It does not rewrite asset rows, update last_checked_at, create symlinks, or repair paths automatically.',
    }); return 0


def command_plan_externalize_assets(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    threshold_bytes = parse_size_bytes(getattr(args, 'threshold', '500M'))
    roots = resolve_external_roots(root, getattr(args, 'primary_root', ''), getattr(args, 'backup_root', ''))
    max_files = max(0, int(getattr(args, 'max_files', 50) or 0))
    max_depth = max(0, int(getattr(args, 'max_depth', 0) or 0))
    large_files = scan_large_files(root, threshold_bytes, max_files=max_files, max_depth=max_depth)
    broken_symlinks = scan_broken_symlinks(root, max_files=max_files, max_depth=max_depth)

    suggestions: list[dict[str, Any]] = []
    for item in large_files:
        path = Path(item['absolute_path'])
        asset_id = item.get('registered_asset_id') or f'asset_{slugify(path.stem)}'
        preview = build_externalization_preview(
            root,
            path,
            asset_id=asset_id,
            primary_root=roots.get('primary_root', ''),
            backup_root=roots.get('backup_root', ''),
            mode=str(getattr(args, 'mode', '') or roots.get('default_mode', 'copy')),
        )
        suggestions.append({
            'path': item['path'],
            'absolute_path': item['absolute_path'],
            'size_bytes': item['size_bytes'],
            'registered_asset_id': item.get('registered_asset_id', ''),
            'suggested_asset_id': asset_id,
            'primary_target': next((t.get('path') for t in preview['targets'] if t.get('role') == 'primary'), ''),
            'backup_target': next((t.get('path') for t in preview['targets'] if t.get('role') == 'backup'), ''),
            'reference_summary': preview['reference_summary'],
        })

    run_and_context_external_refs: list[dict[str, Any]] = []
    known_paths = {normalize_path(asset_path_from_row(root, row)).as_posix() for row in asset_rows(root) if asset_path_from_row(root, row)}
    for manifest_file in sorted((root / 'runs').glob('*/*/RUN_MANIFEST.json')) + sorted((root / 'analysis_runs').glob('*/*/RUN_MANIFEST.json')):
        manifest = read_json(manifest_file)
        for field in ['inputs', 'outputs']:
            for item in manifest.get(field, []) if isinstance(manifest.get(field, []), list) else []:
                if not isinstance(item, dict):
                    continue
                raw = str(item.get('path', '') or '')
                if not raw or not Path(raw).is_absolute():
                    continue
                resolved = normalize_path(Path(raw)).as_posix()
                if resolved.startswith(normalize_path(root).as_posix() + '/'):
                    continue
                if resolved in known_paths:
                    continue
                run_and_context_external_refs.append({'kind': 'run_manifest', 'file': relpath(root, manifest_file), 'field': field, 'path': resolved, 'asset_id': str(item.get('asset_id', ''))})
    for manifest_file in sorted((project_os(root) / 'branches').glob('*/tasks/*/context_manifest.jsonl')):
        for idx, item in enumerate(read_jsonl(manifest_file), start=1):
            if not isinstance(item, dict):
                continue
            raw = str(item.get('path', '') or '')
            if not raw or not Path(raw).is_absolute():
                continue
            resolved = normalize_path(Path(raw)).as_posix()
            if resolved.startswith(normalize_path(root).as_posix() + '/'):
                continue
            if resolved in known_paths:
                continue
            run_and_context_external_refs.append({'kind': 'context_manifest', 'file': relpath(root, manifest_file), 'line': idx, 'path': resolved})

    payload = {
        'generated_at': now_iso(),
        'root': root.as_posix(),
        'threshold': getattr(args, 'threshold', '500M'),
        'threshold_bytes': threshold_bytes,
        'external_assets': {
            'configured_roots': roots.get('roots', []),
            'primary_root': roots.get('primary_root', ''),
            'backup_root': roots.get('backup_root', ''),
            'default_mode': roots.get('default_mode', 'copy'),
            'root_status': [storage_root_status(path) for path in [roots.get('primary_root', ''), roots.get('backup_root', '')] if path],
        },
        'large_file_candidates': large_files,
        'broken_symlinks': broken_symlinks,
        'unregistered_external_references': run_and_context_external_refs,
        'suggestions': suggestions,
        'policy': 'plan-externalize-assets is report-only. It does not copy, move, hard-link, symlink, delete, or rewrite canonical state.',
    }
    if getattr(args, 'write_report', False):
        payload['report_path'] = write_asset_report(root, getattr(args, 'output', DEFAULT_EXTERNALIZE_REPORT_DIR), 'plan_externalize_assets', payload)
    print_json(payload); return 0


def command_externalize_asset(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    if getattr(args, 'mode', 'copy') not in {'copy', 'move'}:
        raise ProjectOSError(f'Invalid externalize mode: {args.mode}')
    if getattr(args, 'apply', False) and not getattr(args, 'approved', False):
        raise ProjectOSError('externalize-asset --apply requires --approved')
    if not getattr(args, 'path', ''):
        raise ProjectOSError('externalize-asset requires --path')

    source_path, _ = project_relative_or_absolute(root, args.path)
    if not source_path.exists():
        raise ProjectOSError(f'Asset path does not exist: {source_path}')
    roots = resolve_external_roots(root, getattr(args, 'primary_root', ''), getattr(args, 'backup_root', ''))
    if not roots.get('primary_root'):
        raise ProjectOSError('externalize-asset requires --primary-root or config.yaml external_assets.default_primary_root')

    existing_row = find_asset_row(root, getattr(args, 'asset_id', '')) if getattr(args, 'asset_id', '') else find_asset_row_by_path(root, source_path)
    asset_id = getattr(args, 'asset_id', '') or (existing_row.get('asset_id', '') if existing_row else f'asset_{timestamp()}__{slugify(source_path.stem)}')
    mode = getattr(args, 'mode', '') or roots.get('default_mode', 'copy')
    preview = build_externalization_preview(
        root,
        source_path,
        asset_id=asset_id,
        primary_root=roots.get('primary_root', ''),
        backup_root=roots.get('backup_root', ''),
        dest_subpath=getattr(args, 'dest_subpath', ''),
        mode=mode,
    )
    primary_target = normalize_path(Path(next(t['path'] for t in preview['targets'] if t.get('role') == 'primary')))
    backup_target = None
    for target in preview['targets']:
        if target.get('role') == 'backup':
            backup_target = normalize_path(Path(target['path']))
            break

    actions: list[dict[str, Any]] = []
    for target in preview['targets']:
        if target.get('exists') and not target.get('checksum_matches_source'):
            raise ProjectOSError(f"Target already exists with different checksum: {target.get('path')}")
        if target.get('exists') and target.get('checksum_matches_source'):
            actions.append({'action': 'reuse_existing', 'role': target.get('role'), 'path': target.get('path')})
        else:
            actions.append({'action': 'copy' if target.get('role') != 'backup' or mode == 'copy' else 'copy', 'role': target.get('role'), 'path': target.get('path')})
    if mode == 'move':
        actions.append({'action': 'remove_source_after_verify', 'path': source_path.as_posix()})

    payload: dict[str, Any] = {
        'root': root.as_posix(),
        'apply': bool(getattr(args, 'apply', False)),
        'approved': bool(getattr(args, 'approved', False)),
        'asset_id': asset_id,
        'mode': mode,
        'preview': preview,
        'actions': actions,
        'policy': 'externalize-asset never uses hard links. Symlinks are not created here and are not canonical state.',
    }
    if not getattr(args, 'apply', False):
        if getattr(args, 'write_report', False):
            payload['report_path'] = write_asset_report(root, getattr(args, 'output', DEFAULT_EXTERNALIZE_REPORT_DIR), 'externalize_asset_dry_run', payload)
        print_json(payload); return 0

    source_checksum = preview['source']['checksum']
    if not primary_target.exists():
        ensure_safe_destination(source_path, primary_target)
        copy_path(source_path, primary_target)
    primary_checksum = checksum_path(primary_target)
    if primary_checksum != source_checksum:
        raise ProjectOSError('Primary target checksum mismatch after copy')

    if backup_target and not backup_target.exists():
        ensure_safe_destination(primary_target, backup_target)
        copy_path(primary_target, backup_target)
    if backup_target and backup_target.exists():
        backup_checksum = checksum_path(backup_target)
        if backup_checksum != source_checksum:
            raise ProjectOSError('Backup target checksum mismatch after copy')

    source_exists_before_cleanup = source_path.exists()
    if mode == 'move' and source_path.exists():
        remove_path(source_path)

    asset_id, asset_row, created = create_or_update_asset_for_externalization(
        root,
        existing_row=existing_row,
        asset_id=asset_id,
        kind=getattr(args, 'kind', '') or (existing_row.get('kind', '') if existing_row else 'data'),
        primary_path=primary_target.as_posix(),
        checksum=source_checksum,
        notes=getattr(args, 'notes', '') or (existing_row.get('notes', '') if existing_row else ''),
        source_note=f'Externalized from {relpath(root, source_path)} via {mode}',
        status='active',
    )

    registered_locations = register_externalization_locations(
        root,
        asset_row=asset_row,
        primary_target=primary_target,
        backup_target=backup_target,
        source_path=source_path,
        source_checksum=source_checksum,
        mode=mode,
        storage_roots=roots.get('effective_roots', []),
    )

    if getattr(args, 'run_id', ''):
        from _task_run import add_run_input
        add_run_input(root, args.run_id, asset_id=asset_id, path=primary_target.as_posix(), name=getattr(args, 'name', '') or asset_id, usage_kind=getattr(args, 'usage_kind', 'input'), notes=getattr(args, 'notes', '') or '', append_event_flag=False)
    elif getattr(args, 'branch_id', '') or getattr(args, 'task_id', ''):
        upsert_asset_usage(root, asset_usage_row(asset_id, branch_id=getattr(args, 'branch_id', '') or current_branch(root), task_id=getattr(args, 'task_id', '') or '', usage_kind=getattr(args, 'usage_kind', 'input'), notes=getattr(args, 'notes', '') or ''))

    sync_primary_locations_from_assets(root)
    refresh_asset_usage(root)
    data_assets_view = refresh_data_assets_markdown(root)
    event_name = 'asset.registered' if created else 'asset.updated'
    append_event(root, event_name, branch_id=getattr(args, 'branch_id', '') or current_branch(root), task_id=getattr(args, 'task_id', '') or '', run_id=getattr(args, 'run_id', '') or '', detail={
        'asset_id': asset_id,
        'command': 'externalize-asset',
        'mode': mode,
        'source_path': preview['source']['path'],
        'primary_path': primary_target.as_posix(),
        'backup_path': backup_target.as_posix() if backup_target else '',
        'externalized': True,
    })
    payload['applied'] = True
    payload['asset'] = asset_row
    payload['registered_locations'] = registered_locations
    payload['data_assets_view'] = data_assets_view
    payload['mapping'] = {'old_path': preview['source']['path'], 'asset_id': asset_id, 'primary_path': primary_target.as_posix(), 'backup_path': backup_target.as_posix() if backup_target else ''}
    if getattr(args, 'write_report', False):
        payload['report_path'] = write_asset_report(root, getattr(args, 'output', DEFAULT_EXTERNALIZE_REPORT_DIR), 'externalize_asset', payload)
    print_json(payload); return 0


def command_adopt_external_asset(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    if getattr(args, 'apply', False) and not getattr(args, 'approved', False):
        raise ProjectOSError('adopt-external-asset --apply requires --approved')
    if not getattr(args, 'path', ''):
        raise ProjectOSError('adopt-external-asset requires --path')

    primary_path, primary_stored = resolve_cli_path(root, getattr(args, 'path', ''))
    if not primary_path.exists():
        raise ProjectOSError(f'External asset path does not exist: {primary_path}')
    if path_within_root(primary_path, root):
        raise ProjectOSError('adopt-external-asset expects an existing path outside the project root; use register-asset or externalize-asset for in-project paths')

    roots = resolve_external_roots(root)
    effective_roots = merge_storage_roots(
        roots.get('effective_roots', []),
        [str(item) for item in getattr(args, 'backup_path', []) or []],
        [str(item) for item in getattr(args, 'mirror_path', []) or []],
        [str(item) for item in getattr(args, 'archive_path', []) or []],
    )
    primary_checksum = checksum_path(primary_path)
    primary_size = size_bytes_for_path(primary_path)
    existing_row = find_asset_row(root, getattr(args, 'asset_id', '')) if getattr(args, 'asset_id', '') else find_asset_row_by_path(root, primary_path)
    asset_id = getattr(args, 'asset_id', '') or (existing_row.get('asset_id', '') if existing_row else default_asset_id_for_path(root, primary_path))

    backup_previews = [
        build_location_preview(root, raw, role='backup', primary_checksum=primary_checksum, storage_roots=effective_roots)
        for raw in getattr(args, 'backup_path', []) or []
    ]
    mirror_previews = [
        build_location_preview(root, raw, role='mirror', primary_checksum=primary_checksum, storage_roots=effective_roots)
        for raw in getattr(args, 'mirror_path', []) or []
    ]
    archive_previews = [
        build_location_preview(root, raw, role='archive', primary_checksum=primary_checksum, storage_roots=effective_roots)
        for raw in getattr(args, 'archive_path', []) or []
    ]
    old_path_previews = []
    for raw in getattr(args, 'old_path', []) or []:
        preview = build_location_preview(root, raw, role='mirror', primary_checksum=primary_checksum, storage_roots=effective_roots)
        if not preview.get('exists', False):
            preview['role'] = 'unavailable'
            preview['status'] = 'missing'
        old_path_previews.append(preview)

    secondary_previews = backup_previews + mirror_previews + archive_previews + old_path_previews
    mismatched = [
        {
            'role': item.get('role', ''),
            'path': item.get('path', ''),
            'absolute_path': item.get('absolute_path', ''),
            'checksum': item.get('checksum', ''),
        }
        for item in secondary_previews
        if item.get('status') == 'stale_checksum'
    ]

    primary_preview = {
        'role': 'primary',
        'path': primary_stored,
        'absolute_path': primary_path.as_posix(),
        'storage_root': storage_root_for_path(primary_path, effective_roots),
        'exists': True,
        'entry_exists': True,
        'is_symlink': primary_path.is_symlink(),
        'inside_project_root': False,
        'size_bytes': primary_size,
        'checksum': primary_checksum,
        'checksum_matches_primary': True,
        'status': 'available',
    }
    primary_refs = structured_path_references(root, primary_path)
    primary_text_refs = text_path_references(root, primary_path)
    legacy_reference_hits = []
    for preview in old_path_previews:
        candidate = Path(str(preview.get('path', '')))
        if candidate.is_absolute():
            ref_source = Path(str(preview.get('absolute_path', '')))
        else:
            ref_source = root / candidate
        legacy_reference_hits.append({
            'path': preview.get('path', ''),
            'absolute_path': preview.get('absolute_path', ''),
            'structured_references': structured_path_references(root, ref_source),
            'text_references': text_path_references(root, ref_source),
        })

    actions: list[dict[str, Any]] = [{
        'action': 'update_asset' if existing_row else 'register_asset',
        'asset_id': asset_id,
        'path': primary_path.as_posix(),
        'kind': getattr(args, 'kind', '') or (existing_row.get('kind', '') if existing_row else 'data'),
    }]
    for item in [primary_preview] + secondary_previews:
        actions.append({'action': 'register_location', 'role': item.get('role', ''), 'path': item.get('path', ''), 'status': item.get('status', '')})
    if getattr(args, 'run_id', ''):
        actions.append({'action': 'link_run_input', 'run_id': getattr(args, 'run_id', ''), 'asset_id': asset_id, 'path': primary_path.as_posix()})
    elif getattr(args, 'branch_id', '') or getattr(args, 'task_id', ''):
        actions.append({'action': 'register_asset_usage', 'branch_id': getattr(args, 'branch_id', '') or current_branch(root), 'task_id': getattr(args, 'task_id', '') or '', 'usage_kind': getattr(args, 'usage_kind', 'input')})

    payload: dict[str, Any] = {
        'root': root.as_posix(),
        'apply': bool(getattr(args, 'apply', False)),
        'approved': bool(getattr(args, 'approved', False)),
        'asset_id': asset_id,
        'existing_asset_id': existing_row.get('asset_id', '') if existing_row else '',
        'primary': primary_preview,
        'secondary_locations': secondary_previews,
        'reference_summary': {
            'primary_structured_count': len(primary_refs),
            'primary_text_count': len(primary_text_refs),
            'legacy_paths_reviewed': len(old_path_previews),
        },
        'structured_references': primary_refs,
        'text_references': primary_text_refs,
        'legacy_reference_hits': legacy_reference_hits,
        'warnings': [{'issue': 'location checksum mismatch', **item} for item in mismatched],
        'actions': actions,
        'policy': 'adopt-external-asset is registry-only. It never copies, moves, hard-links, symlinks, deletes, or rewrites scripts/manifests automatically.',
    }
    if not getattr(args, 'apply', False):
        if getattr(args, 'write_report', False):
            payload['report_path'] = write_asset_report(root, getattr(args, 'output', DEFAULT_EXTERNALIZE_REPORT_DIR), 'adopt_external_asset_dry_run', payload)
        print_json(payload); return 0

    if mismatched:
        raise ProjectOSError('adopt-external-asset found provided locations with a checksum different from the primary asset; review the dry-run report before applying')

    asset_id, asset_row, created = create_or_update_asset_for_externalization(
        root,
        existing_row=existing_row,
        asset_id=asset_id,
        kind=getattr(args, 'kind', '') or (existing_row.get('kind', '') if existing_row else 'data'),
        primary_path=primary_path.as_posix(),
        checksum=primary_checksum,
        notes=getattr(args, 'notes', '') or (existing_row.get('notes', '') if existing_row else ''),
        source_note=f'Adopted in place from existing external path {primary_path.as_posix()}; no copy/move performed.',
        status='active',
    )

    registered_locations: list[dict[str, Any]] = []
    primary_row = {
        'asset_id': asset_id,
        'location_id': build_location_id(asset_id, 'primary', primary_path, str(primary_preview.get('storage_root', ''))),
        'role': 'primary',
        'path': primary_stored,
        'storage_root': str(primary_preview.get('storage_root', '')),
        'status': 'available',
        'size_bytes': str(primary_size),
        'checksum': primary_checksum,
        'registered_at': asset_row.get('registered_at', '') or now_iso(),
        'last_checked_at': now_iso(),
        'notes': 'Canonical primary location adopted in place by adopt-external-asset; no copy/move performed.',
    }
    upsert_asset_location(root, primary_row)
    registered_locations.append(primary_row)

    for item in backup_previews:
        row = asset_location_row_from_preview(
            root,
            asset_id,
            item,
            asset_checksum=primary_checksum,
            notes='Backup location adopted in place by adopt-external-asset; no copy/move performed.',
            registered_at=now_iso(),
        )
        upsert_asset_location(root, row)
        registered_locations.append(row)
    for item in mirror_previews:
        row = asset_location_row_from_preview(
            root,
            asset_id,
            item,
            asset_checksum=primary_checksum,
            notes='Mirror location adopted in place by adopt-external-asset; no copy/move performed.',
            registered_at=now_iso(),
        )
        upsert_asset_location(root, row)
        registered_locations.append(row)
    for item in archive_previews:
        row = asset_location_row_from_preview(
            root,
            asset_id,
            item,
            asset_checksum=primary_checksum,
            notes='Archive location adopted in place by adopt-external-asset; no copy/move performed.',
            registered_at=now_iso(),
        )
        upsert_asset_location(root, row)
        registered_locations.append(row)
    for item in old_path_previews:
        row = asset_location_row_from_preview(
            root,
            asset_id,
            item,
            asset_checksum=primary_checksum,
            notes='Legacy old-path mapping retained for portability/audit; canonical recovery resolves via asset_id + asset_locations.tsv.',
            registered_at=now_iso(),
        )
        upsert_asset_location(root, row)
        registered_locations.append(row)

    if getattr(args, 'run_id', ''):
        from _task_run import add_run_input
        add_run_input(root, args.run_id, asset_id=asset_id, path=primary_path.as_posix(), name=getattr(args, 'name', '') or asset_id, usage_kind=getattr(args, 'usage_kind', 'input'), notes=getattr(args, 'notes', '') or '', append_event_flag=False)
    elif getattr(args, 'branch_id', '') or getattr(args, 'task_id', ''):
        upsert_asset_usage(root, asset_usage_row(asset_id, branch_id=getattr(args, 'branch_id', '') or current_branch(root), task_id=getattr(args, 'task_id', '') or '', usage_kind=getattr(args, 'usage_kind', 'input'), notes=getattr(args, 'notes', '') or ''))

    sync_primary_locations_from_assets(root)
    refresh_asset_usage(root)
    data_assets_view = refresh_data_assets_markdown(root)
    event_name = 'asset.registered' if created else 'asset.updated'
    append_event(root, event_name, branch_id=getattr(args, 'branch_id', '') or current_branch(root), task_id=getattr(args, 'task_id', '') or '', run_id=getattr(args, 'run_id', '') or '', detail={
        'asset_id': asset_id,
        'command': 'adopt-external-asset',
        'primary_path': primary_path.as_posix(),
        'backup_paths': [item.get('path', '') for item in backup_previews],
        'mirror_paths': [item.get('path', '') for item in mirror_previews],
        'archive_paths': [item.get('path', '') for item in archive_previews],
        'old_paths': [item.get('path', '') for item in old_path_previews],
        'externalized': False,
        'adopted_external': True,
    })
    payload['applied'] = True
    payload['asset'] = asset_row
    payload['registered_locations'] = registered_locations
    payload['data_assets_view'] = data_assets_view
    payload['mapping'] = {
        'asset_id': asset_id,
        'primary_path': primary_path.as_posix(),
        'backup_paths': [item.get('path', '') for item in backup_previews],
        'mirror_paths': [item.get('path', '') for item in mirror_previews],
        'archive_paths': [item.get('path', '') for item in archive_previews],
        'old_paths': [item.get('path', '') for item in old_path_previews],
    }
    if getattr(args, 'write_report', False):
        payload['report_path'] = write_asset_report(root, getattr(args, 'output', DEFAULT_EXTERNALIZE_REPORT_DIR), 'adopt_external_asset', payload)
    print_json(payload); return 0


def command_register_asset(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    if args.status not in ASSET_STATUSES: raise ProjectOSError(f'Invalid asset status: {args.status}')
    if not args.path and not args.source_url: raise ProjectOSError('register-asset requires --path or --source-url')
    stored_path = args.path or ''
    path_obj: Path | None = None
    if args.path and not looks_like_url(args.path):
        path_obj, stored_path = project_relative_or_absolute(root, args.path)
        if not path_obj.exists() and not args.allow_missing:
            raise ProjectOSError(f'Asset path does not exist: {path_obj}')
    immutable = args.immutable
    if immutable is None:
        immutable = args.kind.lower() in {'raw', 'reference', 'data', 'dataset', 'input'}
    checksum = args.checksum or ''
    if path_obj and path_obj.exists() and not args.no_checksum and not checksum:
        checksum = checksum_path(path_obj)
    created = now_iso()
    asset_seed = stored_path or args.source_url or args.kind
    asset_id = args.asset_id or f'asset_{timestamp()}__{slugify(Path(asset_seed).stem if not looks_like_url(asset_seed) else asset_seed)}'
    if find_asset_row(root, asset_id): raise ProjectOSError(f'Asset already exists: {asset_id}')
    row = {'asset_id': asset_id, 'kind': args.kind, 'path': stored_path, 'version': args.version or '', 'source_url': args.source_url or '', 'source_note': args.source_note or '', 'immutable': str(bool(immutable)).lower(), 'status': args.status, 'registered_at': created, 'checksum': checksum, 'notes': args.notes or ''}
    upsert_tsv(indexes_dir(root) / 'assets.tsv', INDEX_HEADERS['assets.tsv'], 'asset_id', row)
    usage_payload: dict[str, Any] | None = None
    if args.run_id:
        # Local import avoids a module cycle: _task_run imports asset helpers.
        from _task_run import add_run_input
        usage_payload = add_run_input(root, args.run_id, asset_id=asset_id, path=stored_path, name=args.name or asset_id, usage_kind=args.usage_kind, notes=args.notes or '', append_event_flag=False)
    elif args.branch_id or args.task_id:
        b_id = args.branch_id or current_branch(root)
        usage_row = asset_usage_row(asset_id, branch_id=b_id, task_id=args.task_id or '', usage_kind=args.usage_kind, notes=args.notes or '')
        upsert_asset_usage(root, usage_row)
        usage_payload = usage_row
    sync_primary_locations_from_assets(root)
    refresh_asset_usage(root)
    data_assets_view = refresh_data_assets_markdown(root)
    append_event(root, 'asset.registered', branch_id=args.branch_id or (usage_payload or {}).get('branch_id', '') or current_branch(root), task_id=args.task_id or (usage_payload or {}).get('task_id', ''), run_id=args.run_id or '', detail={'asset_id': asset_id, 'path': stored_path, 'status': args.status, 'usage': bool(usage_payload)})
    print_json({'registered_asset': asset_id, 'asset': row, 'usage': usage_payload or {}, 'data_assets_view': data_assets_view}); return 0


def command_list_assets(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    rows = asset_rows(root)
    if args.kind: rows = [r for r in rows if r.get('kind') == args.kind]
    if args.status: rows = [r for r in rows if r.get('status') == args.status]
    print_json({'assets': rows, 'count': len(rows)}); return 0


def command_show_asset(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    row = find_asset_row(root, args.asset_id)
    if not row: raise ProjectOSError(f'Missing asset: {args.asset_id}')
    usage = [u for u in read_tsv(indexes_dir(root) / 'asset_usage.tsv') if u.get('asset_id') == args.asset_id]
    locations = asset_locations_for_asset(root, args.asset_id)
    checksum_state: dict[str, Any] = {'checked': False}
    target = asset_path_from_row(root, row)
    if target and target.exists() and row.get('checksum'):
        current = checksum_path(target)
        checksum_state = {'checked': True, 'current_checksum': current, 'registered_checksum': row.get('checksum'), 'matches': current == row.get('checksum')}
    elif locations:
        checksum_state = {'checked': False, 'note': 'Canonical path may be externalized; inspect locations for availability/checksum details.'}
    print_json({'asset': row, 'locations': locations, 'usage': usage, 'checksum_state': checksum_state}); return 0


def command_update_asset(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    rows = asset_rows(root)
    found = False
    updated_row: dict[str, Any] = {}
    for row in rows:
        if row.get('asset_id') != args.asset_id:
            continue
        found = True
        if args.status:
            if args.status not in ASSET_STATUSES: raise ProjectOSError(f'Invalid asset status: {args.status}')
            row['status'] = args.status
        for attr, column in [('kind', 'kind'), ('path', 'path'), ('version', 'version'), ('source_url', 'source_url'), ('source_note', 'source_note'), ('notes', 'notes')]:
            value = getattr(args, attr)
            if value is not None:
                row[column] = value
        if args.immutable is not None:
            row['immutable'] = str(bool(args.immutable)).lower()
        if args.checksum is not None:
            row['checksum'] = args.checksum
        if args.rechecksum:
            target = asset_path_from_row(root, row)
            if not target or not target.exists(): raise ProjectOSError(f'Cannot rechecksum missing/non-local asset: {args.asset_id}')
            row['checksum'] = checksum_path(target)
        updated_row = row
    if not found: raise ProjectOSError(f'Missing asset: {args.asset_id}')
    write_tsv(indexes_dir(root) / 'assets.tsv', INDEX_HEADERS['assets.tsv'], rows)
    sync_primary_locations_from_assets(root)
    data_assets_view = refresh_data_assets_markdown(root)
    append_event(root, 'asset.updated', branch_id=current_branch(root), detail={'asset_id': args.asset_id, 'status': updated_row.get('status', '')})
    print_json({'updated_asset': args.asset_id, 'asset': updated_row, 'data_assets_view': data_assets_view}); return 0


def command_checksum_asset(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    row: dict[str, str] | None = None
    if args.asset_id:
        row = find_asset_row(root, args.asset_id)
        if not row: raise ProjectOSError(f'Missing asset: {args.asset_id}')
        target = asset_path_from_row(root, row)
        if not target: raise ProjectOSError(f'Asset has no local checksumable path: {args.asset_id}')
    elif args.path:
        target, _ = project_relative_or_absolute(root, args.path)
    else:
        raise ProjectOSError('checksum-asset requires --asset-id or --path')
    if not target.exists(): raise ProjectOSError(f'Path does not exist: {target}')
    current = checksum_path(target)
    payload = {'path': relpath(root, target), 'checksum': current}
    if row:
        payload.update({'asset_id': row.get('asset_id', ''), 'registered_checksum': row.get('checksum', ''), 'matches': (not row.get('checksum')) or row.get('checksum') == current})
        if args.update:
            rows = asset_rows(root)
            for item in rows:
                if item.get('asset_id') == row.get('asset_id'):
                    item['checksum'] = current
            write_tsv(indexes_dir(root) / 'assets.tsv', INDEX_HEADERS['assets.tsv'], rows)
            sync_primary_locations_from_assets(root)
            data_assets_view = refresh_data_assets_markdown(root)
            append_event(root, 'asset.updated', branch_id=current_branch(root), detail={'asset_id': row.get('asset_id', ''), 'checksum_updated': True})
            payload['updated'] = True
            payload['data_assets_view'] = data_assets_view
    print_json(payload); return 0


def command_refresh_assets(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(); ensure_initialized(root)
    sync_primary_locations_from_assets(root); refresh_asset_usage(root); data_assets_view = refresh_data_assets_markdown(root)
    append_event(root, 'state.updated', branch_id=current_branch(root), detail={'command': 'refresh-assets'})
    print_json({'refreshed': ['.project_os/indexes/asset_locations.tsv', '.project_os/indexes/asset_usage.tsv', data_assets_view.get('path', 'DATA_ASSETS.md')], 'data_assets_view': data_assets_view, 'assets': len(read_tsv(indexes_dir(root) / 'assets.tsv')), 'asset_locations': len(read_tsv(indexes_dir(root) / 'asset_locations.tsv')), 'asset_usage': len(read_tsv(indexes_dir(root) / 'asset_usage.tsv'))}); return 0
