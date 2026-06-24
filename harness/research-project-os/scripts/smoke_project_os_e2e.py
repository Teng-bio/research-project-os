#!/usr/bin/env python3
"""End-to-end smoke test for the research-project-os harness.

The test creates disposable projects under a temporary directory and exercises
the public ``project_os.py`` CLI.  It is intentionally integration-heavy: the
goal is to prove the harness can bootstrap a new project, route short triggers,
track branch/task/run/result/asset/release state, externalize/adopt assets
without hard links, and validate the final canonical indexes.

No real project path or configured external storage root is used.  External
asset tests pass explicit temporary primary/backup roots.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_OS = SCRIPT_DIR / "project_os.py"


class SmokeFailure(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Runner:
    root: Path
    verbose: bool = False
    commands: int = 0
    expected_failures: int = 0
    command_log: list[list[str]] = field(default_factory=list)

    def run(
        self,
        *args: str,
        expect_success: bool = True,
        expect_json: bool = True,
        error_contains: str = "",
    ) -> Any:
        cmd = [sys.executable, PROJECT_OS.as_posix(), *args]
        self.commands += 1
        self.command_log.append(cmd)
        if self.verbose:
            print("+", " ".join(cmd), file=sys.stderr)
        proc = subprocess.run(
            cmd,
            cwd=SCRIPT_DIR,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if expect_success and proc.returncode != 0:
            raise SmokeFailure(
                "command failed\n"
                + f"cmd: {' '.join(cmd)}\n"
                + f"returncode: {proc.returncode}\n"
                + f"stdout: {proc.stdout}\n"
                + f"stderr: {proc.stderr}\n"
            )
        if not expect_success:
            if proc.returncode == 0:
                raise SmokeFailure(f"command unexpectedly succeeded: {' '.join(cmd)}\nstdout: {proc.stdout}")
            self.expected_failures += 1
            if error_contains and error_contains not in (proc.stdout + proc.stderr):
                raise SmokeFailure(
                    f"expected failure text not found: {error_contains!r}\n"
                    + f"cmd: {' '.join(cmd)}\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
                )
        if not expect_json:
            return proc.stdout
        text = proc.stdout.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise SmokeFailure(f"non-JSON output from {' '.join(cmd)}: {text[:1000]}") from exc

    def os(self, subcommand: str, *args: str, **kwargs: Any) -> Any:
        return self.run(subcommand, "--root", self.root.as_posix(), *args, **kwargs)


def assert_true(condition: Any, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def assert_no_hardlink_or_symlink(source: Path, target: Path, label: str) -> None:
    assert_true(source.exists(), f"{label}: missing source {source}")
    assert_true(target.exists(), f"{label}: missing target {target}")
    assert_true(not source.is_symlink(), f"{label}: source should not be symlink")
    assert_true(not target.is_symlink(), f"{label}: target should not be symlink")
    assert_true(not os.path.samefile(source, target), f"{label}: target unexpectedly same file as source")


def write_fixture_files(root: Path) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "results").mkdir(parents=True, exist_ok=True)
    (root / "data/input.fa").write_text(">a\nACGT\n>b\nACGA\n", encoding="utf-8")
    (root / "data/large.bin").write_bytes(b"0123456789abcdef" * 256)
    (root / "docs/analysis_note.md").write_text("# Analysis note\n\nUse data/input.fa.\n", encoding="utf-8")
    (root / "results/tree.nwk").write_text("(a:0.1,b:0.2);\n", encoding="utf-8")
    (root / "results/old_tree.nwk").write_text("(a:0.3,b:0.4);\n", encoding="utf-8")


def exercise_main_project(base: Path, *, verbose: bool = False) -> dict[str, Any]:
    root = base / "new_project"
    primary_root = base / "external_primary"
    backup_root = base / "external_backup"
    adopted_root = base / "already_external"
    primary_root.mkdir(parents=True)
    backup_root.mkdir(parents=True)
    adopted_root.mkdir(parents=True)

    r = Runner(root=root, verbose=verbose)

    dry = r.os(
        "new-project",
        "--title",
        "Smoke RPO Project",
        "--profile",
        "research",
        "--platforms",
        "codex",
        "claude",
        "--no-install-adapters",
        "--no-bootstrap-task",
    )
    assert_true(not dry["applied"], "new-project should be dry-run without --apply")
    r.os(
        "new-project",
        "--title",
        "Smoke RPO Project",
        "--profile",
        "research",
        "--platforms",
        "codex",
        "claude",
        "--no-install-adapters",
        "--no-bootstrap-task",
        "--apply",
    )
    r.os("install-adapters", "--platforms", "codex", "claude")
    r.os("install-adapters", "--platforms", "codex", "claude", "--apply")
    r.os("build-adapters", "--platforms", "codex", "claude")
    assert_true((root / "AGENTS.md").exists(), "codex adapter AGENTS.md missing")
    assert_true((root / "CLAUDE.md").exists(), "claude adapter CLAUDE.md missing")

    write_fixture_files(root)
    r.os("start")
    r.os("status")
    r.os("doctor")
    r.os("doctor", "--repair-plan")

    # Short trigger routing, including triggers absorbed from removed skills.
    route_expectations = {
        "开工": "resume_project",
        "大项目逐步推进": "resume_project",
        "task_plan.md": "project_work_request",
        "写一个项目状态文档": "summarize_state",
        "计算 treeness 和 RCV": "project_work_request",
        "当前结果": "show_current_results",
        "设为当前结果": "promote_result",
    }
    for phrase, expected in route_expectations.items():
        plan = r.os("route", phrase)
        assert_true(plan["intent"] == expected, f"route {phrase!r}: {plan['intent']} != {expected}")
    alias = r.os("explain-trigger", "organize multi-step work")
    assert_true(alias["intent"] == "project_work_request", "explain-trigger alias failed")

    # Branches.
    r.os("create-branch", "--branch-id", "phylo", "--title", "Phylogeny smoke", "--set-current")
    r.os("create-branch", "--branch-id", "archive_me", "--title", "Archive candidate")
    branches = r.os("list-branches")
    assert_true(branches["count"] >= 2, "expected branch rows")
    r.os("show-branch", "--branch-id", "phylo")
    r.os("set-current-branch", "--branch-id", "phylo")
    r.os("archive-branch", "--branch-id", "archive_me", "--status", "archived", "--notes", "smoke archive")

    # Sessions.
    r.os("create-session", "--session-id", "smoke_session", "--branch-id", "phylo", "--set-current")
    r.os("list-sessions")
    r.os("show-session", "--session-id", "smoke_session")
    r.os("set-session-focus", "--session-id", "smoke_session", "--branch-id", "phylo", "--set-current")

    # Tasks and task graph.
    r.os("create-task", "--task-id", "prep_task", "--title", "Prepare inputs", "--kind", "data", "--branch-id", "phylo")
    r.os(
        "create-task",
        "--task-id",
        "smoke_task",
        "--title",
        "Smoke task",
        "--kind",
        "analysis",
        "--branch-id",
        "phylo",
        "--owner",
        "tester",
        "--priority",
        "high",
        "--set-current",
    )
    r.os("list-tasks", "--branch-id", "phylo")
    r.os("show-task", "--task-id", "smoke_task")
    r.os("update-task", "--task-id", "smoke_task", "--owner", "tester2", "--priority", "urgent", "--notes", "updated")
    r.os("update-task-stage", "--task-id", "smoke_task", "--stage", "Run", "--status", "active")
    r.os("add-dependency", "--task-id", "smoke_task", "--depends-on-task", "prep_task")
    r.os("remove-dependency", "--task-id", "smoke_task", "--depends-on-task", "prep_task")
    r.os("add-context", "--task-id", "smoke_task", "--path", "docs/analysis_note.md", "--purpose", "smoke context", "--required")
    r.os("remove-context", "--task-id", "smoke_task", "--path", "docs/analysis_note.md")
    r.os("add-context", "--task-id", "smoke_task", "--path", "docs/analysis_note.md", "--purpose", "smoke context", "--required")
    r.os("set-current-task", "--task-id", "smoke_task")

    # Runs.
    r.os("create-run", "--run-id", "smoke_run", "--task-id", "smoke_task", "--slug", "smoke-run")
    r.os("set-current-run", "--run-id", "smoke_run")
    r.os("update-run", "--run-id", "smoke_run", "--status", "pending_review", "--result-status", "draft")
    r.os("list-runs", "--branch-id", "phylo")
    r.os("show-run", "--run-id", "smoke_run")

    # Assets and run provenance.
    r.os(
        "register-asset",
        "--path",
        "data/input.fa",
        "--asset-id",
        "smoke_input",
        "--kind",
        "data",
        "--branch-id",
        "phylo",
        "--task-id",
        "smoke_task",
        "--run-id",
        "smoke_run",
    )
    r.os("list-assets")
    r.os("show-asset", "--asset-id", "smoke_input")
    r.os("checksum-asset", "--asset-id", "smoke_input")
    r.os("checksum-asset", "--asset-id", "smoke_input", "--update")
    r.os("update-asset", "--asset-id", "smoke_input", "--version", "v1", "--source-note", "smoke", "--rechecksum")
    r.os("refresh-assets")
    r.os("add-run-input", "--run-id", "smoke_run", "--asset-id", "smoke_input", "--name", "input fasta")
    r.os("add-run-command", "--run-id", "smoke_run", "--command", "echo smoke", "--cwd", root.as_posix(), "--exit-code", "0")
    r.os("add-run-output", "--run-id", "smoke_run", "--path", "results/tree.nwk", "--kind", "tree")
    r.os("add-run-output", "--run-id", "smoke_run", "--path", "results/old_tree.nwk", "--kind", "tree")
    r.os("add-run-metric", "--run-id", "smoke_run", "--name", "tip_count", "--value", "2", "--unit", "tips")
    r.os("add-run-parameter", "--run-id", "smoke_run", "--param", 'mode="smoke"', "--param", "bootstrap=100")
    r.os("capture-run-env", "--run-id", "smoke_run")
    r.os("close-run", "--run-id", "smoke_run", "--status", "completed")

    # Approval gates.
    r.os(
        "register-result",
        "--run-id",
        "smoke_run",
        "--path",
        "results/tree.nwk",
        "--status",
        "accepted",
        "--type",
        "artifact",
        "--result-id",
        "gate_result",
        expect_success=False,
        error_contains="requires --approved",
    )
    r.os(
        "register-result",
        "--run-id",
        "smoke_run",
        "--path",
        "results/tree.nwk",
        "--status",
        "candidate",
        "--type",
        "artifact",
        "--title",
        "Smoke tree",
        "--result-id",
        "smoke_result",
    )
    r.os(
        "register-result",
        "--run-id",
        "smoke_run",
        "--path",
        "results/old_tree.nwk",
        "--status",
        "candidate",
        "--type",
        "artifact",
        "--title",
        "Old smoke tree",
        "--result-id",
        "old_result",
    )
    r.os("accept-result", "--result-id", "smoke_result", expect_success=False, error_contains="requires --approved")
    r.os("accept-result", "--result-id", "smoke_result", "--approved")
    r.os("accept-result", "--result-id", "old_result", "--approved")
    r.os(
        "promote-result",
        "--result-id",
        "smoke_result",
        "--to",
        "current/branches/phylo/tree.nwk",
        "--apply",
        expect_success=False,
        error_contains="requires --approved",
    )
    r.os("promote-result", "--result-id", "smoke_result", "--to", "current/branches/phylo/tree.nwk")
    r.os("promote-result", "--result-id", "smoke_result", "--to", "current/branches/phylo/tree.nwk", "--apply", "--approved")
    r.os("supersede-result", "--result-id", "old_result", "--replaced-by", "smoke_result", "--approved")
    r.os("list-results")
    r.os("show-result", "--result-id", "smoke_result")
    current = r.os("show-current", "--branch-id", "phylo", "--audit")
    assert_true(current["count"] == 1, "expected one current branch result")
    assert_true((root / "current/branches/phylo/tree.nwk").exists(), "promoted current result missing")

    # Release workflow.
    r.os(
        "build-release",
        "--release-id",
        "smoke_release",
        "--result-id",
        "smoke_result",
        "--apply",
        expect_success=False,
        error_contains="requires --approved",
    )
    r.os("build-release", "--release-id", "smoke_release", "--result-id", "smoke_result")
    r.os("build-release", "--release-id", "smoke_release", "--result-id", "smoke_result", "--apply", "--approved")
    r.os("list-releases")
    r.os("show-release", "--release-id", "smoke_release")
    valid_release = r.os("validate-release", "--release-id", "smoke_release", "--record")
    assert_true(valid_release["valid"], "release should validate")

    # Externalization: explicit temp primary/backup roots, no hardlink/symlink.
    plan = r.os(
        "plan-externalize-assets",
        "--threshold",
        "1B",
        "--primary-root",
        primary_root.as_posix(),
        "--backup-root",
        backup_root.as_posix(),
        "--max-files",
        "10",
        "--write-report",
    )
    assert_true(plan["large_file_candidates"], "expected large file candidates")
    r.os(
        "externalize-asset",
        "--path",
        "data/large.bin",
        "--asset-id",
        "smoke_large",
        "--primary-root",
        primary_root.as_posix(),
        "--backup-root",
        backup_root.as_posix(),
        "--mode",
        "copy",
        "--apply",
        expect_success=False,
        error_contains="requires --approved",
    )
    dry_external = r.os(
        "externalize-asset",
        "--path",
        "data/large.bin",
        "--asset-id",
        "smoke_large",
        "--primary-root",
        primary_root.as_posix(),
        "--backup-root",
        backup_root.as_posix(),
        "--mode",
        "copy",
        "--write-report",
    )
    assert_true("Hard links are forbidden" in dry_external["preview"]["policy"], "externalization policy missing no-hardlink text")
    applied_external = r.os(
        "externalize-asset",
        "--path",
        "data/large.bin",
        "--asset-id",
        "smoke_large",
        "--primary-root",
        primary_root.as_posix(),
        "--backup-root",
        backup_root.as_posix(),
        "--mode",
        "copy",
        "--branch-id",
        "phylo",
        "--task-id",
        "smoke_task",
        "--run-id",
        "smoke_run",
        "--write-report",
        "--apply",
        "--approved",
    )
    source_large = root / "data/large.bin"
    primary_large = Path(applied_external["mapping"]["primary_path"])
    backup_large = Path(applied_external["mapping"]["backup_path"])
    assert_no_hardlink_or_symlink(source_large, primary_large, "external primary")
    assert_no_hardlink_or_symlink(source_large, backup_large, "external backup")
    locs = r.os("list-asset-locations", "--asset-id", "smoke_large")
    roles = {row["role"] for row in locs["asset_locations"]}
    assert_true({"primary", "backup", "mirror"} <= roles, f"external location roles incomplete: {roles}")
    verify = r.os("verify-external-assets", "--asset-id", "smoke_large", "--checksum")
    assert_true(verify["ok"], f"external asset verification warnings: {verify['warnings']}")

    # Adopt an already external asset; registry-only and no copy/move.
    adopted_primary = adopted_root / "adopted.fa"
    adopted_backup = adopted_root / "adopted.backup.fa"
    adopted_mirror = adopted_root / "adopted.mirror.fa"
    adopted_archive = adopted_root / "adopted.archive.fa"
    for path in [adopted_primary, adopted_backup, adopted_mirror, adopted_archive]:
        path.write_text(">x\nAAAA\n", encoding="utf-8")
    r.os(
        "adopt-external-asset",
        "--path",
        adopted_primary.as_posix(),
        "--asset-id",
        "adopted_external",
        "--apply",
        expect_success=False,
        error_contains="requires --approved",
    )
    adopt_dry = r.os(
        "adopt-external-asset",
        "--path",
        adopted_primary.as_posix(),
        "--asset-id",
        "adopted_external",
        "--backup-path",
        adopted_backup.as_posix(),
        "--mirror-path",
        adopted_mirror.as_posix(),
        "--archive-path",
        adopted_archive.as_posix(),
        "--old-path",
        "data/legacy_adopted.fa",
        "--write-report",
    )
    assert_true("registry-only" in adopt_dry["policy"], "adopt policy should be registry-only")
    r.os(
        "adopt-external-asset",
        "--path",
        adopted_primary.as_posix(),
        "--asset-id",
        "adopted_external",
        "--backup-path",
        adopted_backup.as_posix(),
        "--mirror-path",
        adopted_mirror.as_posix(),
        "--archive-path",
        adopted_archive.as_posix(),
        "--old-path",
        "data/legacy_adopted.fa",
        "--branch-id",
        "phylo",
        "--task-id",
        "smoke_task",
        "--run-id",
        "smoke_run",
        "--write-report",
        "--apply",
        "--approved",
    )
    adopted_verify = r.os("verify-external-assets", "--asset-id", "adopted_external", "--checksum")
    assert_true(adopted_verify["ok"], f"adopted asset verification warnings: {adopted_verify['warnings']}")
    assert_true(adopted_primary.exists(), "adopt-external-asset should not move/delete primary")

    # Decisions, handoff, derived dashboards, hooks, and recovery reports.
    body_file = root / "docs/decision.md"
    body_file.write_text("Use no-hardlink external assets.\n", encoding="utf-8")
    r.os("record-decision", "--decision-id", "decision_no_hardlink", "--title", "No hardlink", "--body-file", "docs/decision.md")
    r.os("list-decisions")
    r.os("update-handoff", "--scope", "task", "--task-id", "smoke_task", "--message", "Smoke test handoff")
    r.os("summarize-state", "--recent-events", "5")
    dash_dry = r.os("export-dashboard")
    assert_true(not dash_dry.get("applied", False), "dashboard without --apply should be dry-run")
    r.os("export-dashboard", "--apply", "--sqlite")
    r.os("list-hooks")
    r.os("dispatch-hooks", "--limit", "2", "--kind", "reminder", "--write-report")
    r.os("dispatch-hooks", "--event", "run.closed", "--limit", "1", "--kind", "session_summary")
    r.os("plan-recovery", "--write-report")
    r.os("migrate-branch-first")

    # Session close / cleanup is report-only for cleanup planner.
    r.os("pause-session", "--session-id", "smoke_session", "--notes", "pause smoke")
    r.os("plan-session-cleanup", "--status", "paused", "--write-report")
    r.os("resume-session", "--session-id", "smoke_session", "--set-current")
    r.os("close-session", "--session-id", "smoke_session", "--notes", "close smoke")
    r.os("plan-session-cleanup", "--status", "closed", "--write-report")
    r.os("set-current-session", "--clear")

    # Close the prep task; leave smoke_task active to represent resumable work.
    r.os("close-task", "--task-id", "prep_task", "--status", "completed")

    r.os("refresh-indexes")
    validation = r.os("validate")
    assert_true(validation.get("errors", 0) == 0, f"validate errors: {validation}")
    assert_true(validation.get("warnings", 0) == 0, f"validate warnings: {validation}")

    # Inspect important generated/canonical artifacts directly.
    required_paths = [
        ".project_os/indexes/branches.tsv",
        ".project_os/indexes/tasks.tsv",
        ".project_os/indexes/runs.tsv",
        ".project_os/indexes/results.tsv",
        ".project_os/indexes/assets.tsv",
        ".project_os/indexes/asset_locations.tsv",
        ".project_os/indexes/releases.tsv",
        ".project_os/journals/events.jsonl",
        "RUNS_INDEX.tsv",
        "RESULTS_INDEX.md",
        "DATA_ASSETS.md",
        "release/smoke_release/MANIFEST.tsv",
        "release/smoke_release/CHECKSUMS.tsv",
        ".project_os/exports/dashboard.json",
        ".project_os/exports/dashboard.html",
        ".project_os/exports/dashboard.sqlite",
    ]
    for rel in required_paths:
        assert_true((root / rel).exists(), f"missing generated artifact: {rel}")

    return {
        "root": root.as_posix(),
        "commands": r.commands,
        "expected_failures": r.expected_failures,
        "validate": validation,
        "external_primary": primary_large.as_posix(),
        "external_backup": backup_large.as_posix(),
        "asset_location_roles": sorted(roles),
    }


def exercise_restore_journal(base: Path, *, verbose: bool = False) -> dict[str, Any]:
    root = base / "restore_journal_project"
    r = Runner(root=root, verbose=verbose)
    r.os("init", "--title", "Restore journal fixture", "--apply")
    journal = root / ".project_os/journals/events.jsonl"
    assert_true(journal.exists(), "fixture journal missing after init")
    journal.unlink()
    dry = r.os("restore-journal")
    assert_true(not dry["applied"] and not dry["restored"], "restore-journal dry-run should not restore")
    r.os("restore-journal", "--apply", expect_success=False, error_contains="requires --approved")
    applied = r.os("restore-journal", "--apply", "--approved", "--reason", "smoke missing journal")
    assert_true(applied["restored"], "restore-journal apply did not restore")
    validation = r.os("validate")
    assert_true(validation.get("errors", 0) == 0, f"restore fixture validate errors: {validation}")
    return {"root": root.as_posix(), "commands": r.commands, "expected_failures": r.expected_failures}


def exercise_protected_data_assets(base: Path, *, verbose: bool = False) -> dict[str, Any]:
    root = base / "protected_data_assets_project"
    r = Runner(root=root, verbose=verbose)
    r.os("init", "--title", "Protected DATA_ASSETS fixture", "--apply")
    human_text = "# DATA_ASSETS\n\nHuman-authored source registry. Do not overwrite.\n"
    (root / "DATA_ASSETS.md").write_text(human_text, encoding="utf-8")
    (root / "data").mkdir(exist_ok=True)
    (root / "data/protected.fa").write_text(">p\nCCCC\n", encoding="utf-8")
    r.os("register-asset", "--path", "data/protected.fa", "--asset-id", "protected_asset", "--kind", "data")
    r.os("refresh-indexes")
    assert_true((root / "DATA_ASSETS.md").read_text(encoding="utf-8") == human_text, "human DATA_ASSETS.md was overwritten")
    generated = root / ".project_os/exports/views/DATA_ASSETS.generated.md"
    assert_true(generated.exists(), "protected DATA_ASSETS generated export missing")
    validation = r.os("validate")
    assert_true(validation.get("errors", 0) == 0, f"protected fixture validate errors: {validation}")
    assert_true(validation.get("warnings", 0) == 0, f"protected fixture validate warnings: {validation}")
    return {"root": root.as_posix(), "commands": r.commands, "expected_failures": r.expected_failures}


def exercise_migration_fixture(base: Path, *, verbose: bool = False) -> dict[str, Any]:
    root = base / "migration_fixture"
    r = Runner(root=root, verbose=verbose)
    r.os("init", "--title", "Migration fixture", "--apply")
    # A conservative migration smoke: dry-run the branch-first migrator on an
    # already initialized fixture. This proves the command can inspect current
    # state without mutating or requiring destructive moves.
    dry = r.os("migrate-branch-first", "--mode", "copy")
    assert_true("dry_run_migration" in dry, "migration dry-run payload missing")
    return {"root": root.as_posix(), "commands": r.commands, "expected_failures": r.expected_failures}


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    if args.base_dir:
        base = Path(args.base_dir).expanduser().resolve()
        if base.exists() and any(base.iterdir()) and not args.keep:
            raise SmokeFailure("--base-dir must be empty unless --keep is set")
        base.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        base = Path(tempfile.mkdtemp(prefix="research_project_os_e2e_"))
        cleanup = not args.keep

    summary: dict[str, Any] = {"base": base.as_posix(), "kept": bool(args.keep), "fixtures": {}}
    try:
        summary["fixtures"]["main"] = exercise_main_project(base, verbose=args.verbose)
        summary["fixtures"]["restore_journal"] = exercise_restore_journal(base, verbose=args.verbose)
        summary["fixtures"]["protected_data_assets"] = exercise_protected_data_assets(base, verbose=args.verbose)
        summary["fixtures"]["migration"] = exercise_migration_fixture(base, verbose=args.verbose)
        summary["commands"] = sum(item.get("commands", 0) for item in summary["fixtures"].values())
        summary["expected_failures"] = sum(item.get("expected_failures", 0) for item in summary["fixtures"].values())
        summary["ok"] = True
        return summary
    finally:
        if cleanup:
            shutil.rmtree(base, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run disposable end-to-end smoke tests for research-project-os.")
    parser.add_argument("--base-dir", default="", help="Optional empty directory for fixtures. Defaults to a temporary directory.")
    parser.add_argument("--keep", action="store_true", help="Keep temporary fixtures for inspection.")
    parser.add_argument("--verbose", action="store_true", help="Print each project_os.py command to stderr.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = run_smoke(args)
    except SmokeFailure as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
