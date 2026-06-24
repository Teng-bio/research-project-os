from __future__ import annotations

from pathlib import Path

from _schema import OS_DIR


def project_os(root: Path) -> Path:
    return root / OS_DIR


def indexes_dir(root: Path) -> Path:
    return project_os(root) / 'indexes'


def relpath(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def branch_dir(root: Path, branch_id: str) -> Path:
    return project_os(root) / 'branches' / branch_id


def branch_task_dir(root: Path, branch_id: str, task_id: str) -> Path:
    return branch_dir(root, branch_id) / 'tasks' / task_id


def branch_current_dir(root: Path, branch_id: str) -> Path:
    return root / 'current' / 'branches' / branch_id


def run_dir(root: Path, branch_id: str, run_id: str, run_root: str = 'runs') -> Path:
    return root / run_root / branch_id / run_id


def project_relative_or_absolute(root: Path, raw: str) -> tuple[Path, str]:
    path = Path(raw).expanduser()
    if path.is_absolute():
        resolved = path.resolve(); return resolved, relpath(root, resolved)
    return (root / path).resolve(), path.as_posix()
