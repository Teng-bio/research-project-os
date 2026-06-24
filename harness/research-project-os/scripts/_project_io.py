from __future__ import annotations

import csv
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from _paths import project_os


class ProjectOSError(Exception):
    pass


POINTER_NAMES = {'current_branch', 'current_task', 'current_run'}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def timestamp() -> str:
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def slugify(text: str, max_len: int = 48) -> str:
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', text.strip().lower())
    slug = re.sub(r'_+', '_', slug).strip('_')
    return (slug or 'item')[:max_len].strip('_') or 'item'


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def validate_session_id(session_id: str) -> str:
    session_id = str(session_id or '').strip()
    if not session_id:
        raise ProjectOSError('Missing session_id')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', session_id):
        raise ProjectOSError(f'Invalid session_id: {session_id}. Use letters, numbers, dot, dash, or underscore; start with a letter/number.')
    if session_id in {'.', '..'}:
        raise ProjectOSError(f'Invalid session_id: {session_id}')
    return session_id


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise ProjectOSError(f'Missing JSON file: {path}') from exc
    except json.JSONDecodeError as exc:
        raise ProjectOSError(f'Malformed JSON file: {path}: {exc}') from exc
    if not isinstance(data, dict):
        raise ProjectOSError(f'Expected JSON object: {path}')
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle, delimiter='\t'))


def write_tsv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        for row in rows:
            writer.writerow({h: '' if row.get(h) is None else str(row.get(h, '')) for h in headers})
    os.replace(tmp, path)


class AdvisoryLock:
    def __init__(self, root: Path, timeout: float = 5.0):
        self.root = root
        self.timeout = timeout
        self.path = project_os(root) / 'runtime' / 'lock'
        self.acquired = False

    def __enter__(self) -> 'AdvisoryLock':
        self.path.parent.mkdir(parents=True, exist_ok=True)
        start = time.time()
        payload = {'pid': os.getpid(), 'created_at': now_iso(), 'command': 'project_os.py'}
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False) + '\n')
                self.acquired = True
                return self
            except FileExistsError:
                if time.time() - start >= self.timeout:
                    raise ProjectOSError(f'Harness lock exists: {self.path}. If no project_os.py process is running, remove it after review.')
                time.sleep(0.1)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def harness_lock(root: Path) -> AdvisoryLock:
    return AdvisoryLock(root)


def upsert_tsv(path: Path, headers: list[str], key: str, row: dict[str, Any]) -> None:
    rows = read_tsv(path)
    out: list[dict[str, Any]] = []
    seen = False
    for existing in rows:
        if existing.get(key) == str(row.get(key, '')):
            merged = {h: row.get(h, '') for h in headers}
            out.append(merged)
            seen = True
        else:
            out.append({h: existing.get(h, '') for h in headers})
    if not seen:
        out.append({h: row.get(h, '') for h in headers})
    write_tsv(path, headers, out)


def events_path(root: Path) -> Path:
    return project_os(root) / 'journals' / 'events.jsonl'


def append_event(root: Path, event: str, *, branch_id: str = '', task_id: str = '', run_id: str = '', result_id: str = '', actor: str = 'cli', detail: dict[str, Any] | None = None) -> None:
    path = events_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'ts': now_iso(),
        'event': event,
        'actor': actor,
        'branch_id': branch_id,
        'task_id': task_id,
        'run_id': run_id,
        'result_id': result_id,
        'detail': detail or {},
    }
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')


def runtime_dir(root: Path) -> Path:
    return project_os(root) / 'runtime'


def sessions_dir(root: Path) -> Path:
    return runtime_dir(root) / 'sessions'


def session_dir(root: Path, session_id: str) -> Path:
    return sessions_dir(root) / validate_session_id(session_id)


def raw_pointer_path(root: Path, name: str) -> Path:
    if name not in POINTER_NAMES:
        raise ProjectOSError(f'Invalid runtime pointer name: {name}')
    return runtime_dir(root) / name


def session_pointer_path(root: Path, session_id: str, name: str) -> Path:
    if name not in POINTER_NAMES:
        raise ProjectOSError(f'Invalid runtime pointer name: {name}')
    return session_dir(root, session_id) / name


def current_session(root: Path) -> str:
    path = runtime_dir(root) / 'current_session'
    return path.read_text(encoding='utf-8').strip() if path.exists() else ''


def set_current_session(root: Path, session_id: str) -> None:
    if session_id:
        validate_session_id(session_id)
    path = runtime_dir(root) / 'current_session'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(session_id.strip() + ('\n' if session_id.strip() else ''), encoding='utf-8')


def raw_current_pointer(root: Path, name: str) -> str:
    path = raw_pointer_path(root, name)
    return path.read_text(encoding='utf-8').strip() if path.exists() else ''


def pointer_path(root: Path, name: str, session_id: str | None = None) -> Path:
    if session_id:
        return session_pointer_path(root, session_id, name)
    active_session = current_session(root)
    if active_session:
        return session_pointer_path(root, active_session, name)
    return raw_pointer_path(root, name)


def current_pointer(root: Path, name: str, session_id: str | None = None) -> str:
    path = pointer_path(root, name, session_id=session_id)
    return path.read_text(encoding='utf-8').strip() if path.exists() else ''


def set_global_pointer(root: Path, name: str, value: str) -> None:
    path = raw_pointer_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.strip() + ('\n' if value.strip() else ''), encoding='utf-8')


def set_pointer(root: Path, name: str, value: str, session_id: str | None = None) -> None:
    path = pointer_path(root, name, session_id=session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.strip() + ('\n' if value.strip() else ''), encoding='utf-8')


def focus_payload(root: Path, session_id: str | None = None) -> dict[str, str]:
    active_session = session_id or current_session(root)
    return {
        'session_id': active_session,
        'source': 'session' if active_session else 'global',
        'current_branch': current_pointer(root, 'current_branch', session_id=active_session or None),
        'current_task': current_pointer(root, 'current_task', session_id=active_session or None),
        'current_run': current_pointer(root, 'current_run', session_id=active_session or None),
    }


def write_missing_text_if_absent(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(text, encoding='utf-8')


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            item = {'_error': 'malformed_jsonl', 'raw': line}
        if isinstance(item, dict):
            rows.append(item)
    return rows
