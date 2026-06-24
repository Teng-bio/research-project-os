from __future__ import annotations

import html
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from _hooks import DEFAULT_DISPATCH_KINDS, HOOK_KINDS, parse_hooks_config
from _recovery import build_recovery_plan
from _views import current_result_views, promotion_audit


def read_recent_events(ctx: Any, root: Path, limit: int = 20) -> list[dict[str, Any]]:
    rows = ctx.read_jsonl(ctx.events_path(root)) if ctx.events_path(root).exists() else []
    return rows[-limit:] if limit else rows


def graph_node(node_id: str, kind: str, label: str, **attrs: Any) -> dict[str, Any]:
    return {'id': node_id, 'kind': kind, 'label': label, **{k: v for k, v in attrs.items() if v not in (None, '')}}


def graph_edge(source: str, target: str, relation: str, **attrs: Any) -> dict[str, Any]:
    return {'source': source, 'target': target, 'relation': relation, **{k: v for k, v in attrs.items() if v not in (None, '')}}


def build_graph(rows: dict[str, list[dict[str, str]]], sessions: dict[str, Any] | None = None) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    def add_node(node: dict[str, Any]) -> None:
        node_id = str(node.get('id', ''))
        if not node_id or node_id in node_ids:
            return
        node_ids.add(node_id)
        nodes.append(node)

    def add_edge(edge: dict[str, Any]) -> None:
        if edge.get('source') and edge.get('target'):
            edges.append(edge)

    def ensure_focus_target(node_id: str, kind: str, label: str) -> None:
        if node_id not in node_ids:
            add_node(graph_node(node_id, kind, label, missing=True))

    add_node(graph_node('project:root', 'project', 'Project'))
    for branch in rows.get('branches', []):
        branch_id = branch.get('branch_id', '')
        if not branch_id:
            continue
        add_node(graph_node(f'branch:{branch_id}', 'branch', branch.get('title') or branch_id, status=branch.get('status'), path=branch.get('branch_path')))
        add_edge(graph_edge('project:root', f'branch:{branch_id}', 'has_branch'))
        if branch.get('parent_branch_id'):
            add_edge(graph_edge(f'branch:{branch.get("parent_branch_id")}', f'branch:{branch_id}', 'parent_branch'))
    for task in rows.get('tasks', []):
        task_id = task.get('task_id', '')
        if not task_id:
            continue
        add_node(graph_node(f'task:{task_id}', 'task', task.get('title') or task_id, status=task.get('status'), stage=task.get('stage'), path=task.get('task_path')))
        if task.get('branch_id'):
            add_edge(graph_edge(f'branch:{task.get("branch_id")}', f'task:{task_id}', 'owns_task'))
        if task.get('parent_task_id'):
            add_edge(graph_edge(f'task:{task.get("parent_task_id")}', f'task:{task_id}', 'parent_task'))
    for run in rows.get('runs', []):
        run_id = run.get('run_id', '')
        if not run_id:
            continue
        add_node(graph_node(f'run:{run_id}', 'run', run_id, status=run.get('status'), result_status=run.get('result_status'), path=run.get('run_path')))
        if run.get('branch_id'):
            add_edge(graph_edge(f'branch:{run.get("branch_id")}', f'run:{run_id}', 'owns_run'))
        if run.get('task_id'):
            add_edge(graph_edge(f'task:{run.get("task_id")}', f'run:{run_id}', 'has_run'))
    for result in rows.get('results', []):
        result_id = result.get('result_id', '')
        if not result_id:
            continue
        add_node(graph_node(f'result:{result_id}', 'result', result.get('title') or result_id, status=result.get('status'), type=result.get('type'), path=result.get('path')))
        if result.get('branch_id'):
            add_edge(graph_edge(f'branch:{result.get("branch_id")}', f'result:{result_id}', 'owns_result'))
        if result.get('task_id'):
            add_edge(graph_edge(f'task:{result.get("task_id")}', f'result:{result_id}', 'has_result'))
        if result.get('run_id'):
            add_edge(graph_edge(f'run:{result.get("run_id")}', f'result:{result_id}', 'produced_result'))
        if result.get('replaced_by'):
            add_edge(graph_edge(f'result:{result_id}', f'result:{result.get("replaced_by")}', 'superseded_by'))
        for target in [item for item in result.get('promoted_to', '').split(',') if item]:
            target_id = f'current:{target}'
            add_node(graph_node(target_id, 'current_target', target, path=target))
            add_edge(graph_edge(f'result:{result_id}', target_id, 'promoted_to'))
    for asset in rows.get('assets', []):
        asset_id = asset.get('asset_id', '')
        if not asset_id:
            continue
        add_node(graph_node(f'asset:{asset_id}', 'asset', asset_id, type=asset.get('kind'), status=asset.get('status'), path=asset.get('path') or asset.get('source_url')))
    for location in rows.get('asset_locations', []):
        location_id = location.get('location_id', '')
        asset_id = location.get('asset_id', '')
        if not location_id:
            continue
        add_node(graph_node(f'asset_location:{location_id}', 'asset_location', location_id, role=location.get('role'), status=location.get('status'), path=location.get('path')))
        if asset_id:
            add_edge(graph_edge(f'asset:{asset_id}', f'asset_location:{location_id}', 'has_location'))
    for usage in rows.get('asset_usage', []):
        if usage.get('asset_id') and usage.get('run_id'):
            add_edge(graph_edge(f'asset:{usage.get("asset_id")}', f'run:{usage.get("run_id")}', f'asset_{usage.get("usage_kind") or "used_by"}', task_id=usage.get('task_id'), result_id=usage.get('result_id')))
        if usage.get('asset_id') and usage.get('result_id'):
            add_edge(graph_edge(f'asset:{usage.get("asset_id")}', f'result:{usage.get("result_id")}', 'asset_result_link', usage_kind=usage.get('usage_kind')))
    for release in rows.get('releases', []):
        release_id = release.get('release_id', '')
        if not release_id:
            continue
        add_node(graph_node(f'release:{release_id}', 'release', release_id, status=release.get('status'), path=release.get('path')))
        for branch_id in [item for item in release.get('source_branch_ids', '').split(',') if item]:
            add_edge(graph_edge(f'branch:{branch_id}', f'release:{release_id}', 'source_branch'))
        for result_id in [item for item in release.get('source_result_ids', '').split(',') if item]:
            add_edge(graph_edge(f'result:{result_id}', f'release:{release_id}', 'released_as'))

    session_payload = sessions or {}
    current_session = str(session_payload.get('current_session', '')) if isinstance(session_payload, dict) else ''
    session_rows = session_payload.get('sessions', []) if isinstance(session_payload, dict) else []
    for session in session_rows if isinstance(session_rows, list) else []:
        session_id = str(session.get('session_id', ''))
        if not session_id:
            continue
        session_node = f'session:{session_id}'
        add_node(graph_node(
            session_node,
            'session',
            session_id,
            status=session.get('status'),
            is_current=str(bool(session.get('is_current'))).lower(),
            updated_at=session.get('updated_at'),
        ))
        add_edge(graph_edge('project:root', session_node, 'has_session'))
        if session_id == current_session or session.get('is_current'):
            add_edge(graph_edge('project:root', session_node, 'active_session'))
        branch_id = str(session.get('current_branch', ''))
        task_id = str(session.get('current_task', ''))
        run_id = str(session.get('current_run', ''))
        if branch_id:
            target = f'branch:{branch_id}'
            ensure_focus_target(target, 'missing_branch', branch_id)
            add_edge(graph_edge(session_node, target, 'focus_branch'))
        if task_id:
            target = f'task:{task_id}'
            ensure_focus_target(target, 'missing_task', task_id)
            add_edge(graph_edge(session_node, target, 'focus_task'))
        if run_id:
            target = f'run:{run_id}'
            ensure_focus_target(target, 'missing_run', run_id)
            add_edge(graph_edge(session_node, target, 'focus_run'))

    node_kind_counts: dict[str, int] = {}
    edge_relation_counts: dict[str, int] = {}
    for node in nodes:
        kind = str(node.get('kind', ''))
        node_kind_counts[kind] = node_kind_counts.get(kind, 0) + 1
    for edge in edges:
        relation = str(edge.get('relation', ''))
        edge_relation_counts[relation] = edge_relation_counts.get(relation, 0) + 1
    return {
        'nodes': nodes,
        'edges': edges,
        'counts': {'nodes': len(nodes), 'edges': len(edges), 'node_kinds': node_kind_counts, 'edge_relations': edge_relation_counts},
        'policy': 'Generated graph view only. It is derived from canonical indexes/current targets and must not be edited as state.',
    }


def build_session_focus_view(sessions: dict[str, Any]) -> dict[str, Any]:
    session_rows = sessions.get('sessions', []) if isinstance(sessions, dict) else []
    active_focus = sessions.get('active_focus', {}) if isinstance(sessions, dict) else {}
    current_session = str(sessions.get('current_session', '')) if isinstance(sessions, dict) else ''
    status_counts: dict[str, int] = {}
    current_row: dict[str, Any] = {}
    stale_current = False
    for row in session_rows if isinstance(session_rows, list) else []:
        status = str(row.get('status', '') or '(unknown)')
        status_counts[status] = status_counts.get(status, 0) + 1
        if row.get('session_id') == current_session:
            current_row = dict(row)
            if status != 'active':
                stale_current = True
    return {
        'current_session': current_session,
        'active_focus': active_focus,
        'current_session_row': current_row,
        'status_counts': status_counts,
        'count': len(session_rows) if isinstance(session_rows, list) else 0,
        'active_count': status_counts.get('active', 0),
        'paused_count': status_counts.get('paused', 0),
        'closed_count': status_counts.get('closed', 0),
        'stale_current_session': stale_current,
        'policy': 'Generated session focus view only. Sessions shadow runtime focus and do not create canonical branch/task/run identities.',
    }


def build_session_cleanup_view(ctx: Any, root: Path) -> dict[str, Any]:
    if not hasattr(ctx, 'build_session_cleanup_plan'):
        return {
            'candidate_count': 0,
            'candidates': [],
            'policy': 'Generated session cleanup view unavailable; cleanup planner not loaded.',
        }
    plan = ctx.build_session_cleanup_plan(root, statuses=['closed'], min_age_days=0, include_current=False)
    return {
        'generated_at': plan.get('generated_at', ''),
        'candidate_count': plan.get('candidate_count', 0),
        'skipped_count': plan.get('skipped_count', 0),
        'warning_count': plan.get('warning_count', 0),
        'candidates': plan.get('candidates', []),
        'warnings': plan.get('warnings', []),
        'policy': 'Generated session cleanup candidate view only. It does not delete, move, archive, or rewrite session runtime directories.',
        'suggested_command': 'python scripts/project_os.py plan-session-cleanup --root <project> --status closed',
    }


def build_hooks_view(ctx: Any, root: Path) -> dict[str, Any]:
    config = parse_hooks_config(root)
    event_source = str(config.get('event_source') or '.project_os/journals/events.jsonl')
    event_source_path = Path(event_source).expanduser()
    if not event_source_path.is_absolute():
        event_source_path = root / event_source_path
    events = ctx.read_jsonl(event_source_path) if event_source_path.exists() else []
    malformed_count = sum(1 for event in events if event.get('_error'))
    latest_event = ''
    for event in reversed(events):
        if not event.get('_error'):
            latest_event = str(event.get('event', ''))
            break
    report_dir = root / '.project_os' / 'exports' / 'hooks'
    report_count = len(list(report_dir.glob('hook_report_*.json'))) if report_dir.exists() else 0
    allowed_kinds = [str(kind) for kind in config.get('allowed_kinds', [])]
    unknown_allowed_kinds = [kind for kind in allowed_kinds if kind not in HOOK_KINDS]
    active_like = bool(config.get('enabled')) or str(config.get('mode', '')).lower() not in {'', 'disabled'} or str(config.get('dispatcher', '')).lower() not in {'', 'none'}
    return {
        'active_dispatcher_enabled': False,
        'manual_dispatcher_available': True,
        'config': config,
        'config_exists': bool(config.get('exists')),
        'config_requests_active_dispatcher': active_like,
        'known_kinds': HOOK_KINDS,
        'default_manual_kinds': DEFAULT_DISPATCH_KINDS,
        'allowed_kinds': allowed_kinds,
        'unknown_allowed_kinds': unknown_allowed_kinds,
        'event_source': ctx.relpath(root, event_source_path) if event_source_path.exists() else event_source,
        'event_source_exists': event_source_path.exists(),
        'event_count': len(events),
        'malformed_event_count': malformed_count,
        'latest_event': latest_event,
        'generated_report_dir': ctx.relpath(root, report_dir),
        'generated_report_count': report_count,
        'suggested_status_command': 'python scripts/project_os.py list-hooks --root <project>',
        'suggested_report_command': 'python scripts/project_os.py dispatch-hooks --root <project> --limit 1',
        'policy': 'Generated hooks status view only. Active automatic hooks remain disabled; manual reports may read events and suggest CLI commands but must not edit canonical state.',
    }


def build_recovery_view(root: Path) -> dict[str, Any]:
    plan = build_recovery_plan(root, include_dashboard_staleness=False)
    return {
        'generated_at': plan.get('generated_at', ''),
        'summary': plan.get('summary', {}),
        'lock': plan.get('lock', {}),
        'tmp_file_count': (plan.get('tmp_files', {}) if isinstance(plan.get('tmp_files', {}), dict) else {}).get('count', 0),
        'malformed_event_count': (plan.get('event_journal', {}) if isinstance(plan.get('event_journal', {}), dict) else {}).get('malformed_event_count', 0),
        'missing_required_count': (plan.get('required_paths', {}) if isinstance(plan.get('required_paths', {}), dict) else {}).get('missing_required_count', 0),
        'pointer_issue_count': (plan.get('pointers', {}) if isinstance(plan.get('pointers', {}), dict) else {}).get('issue_count', 0),
        'index_drift_count': (plan.get('index_drift', {}) if isinstance(plan.get('index_drift', {}), dict) else {}).get('drift_count', 0),
        'stale_generated_view_count': (plan.get('generated_views', {}) if isinstance(plan.get('generated_views', {}), dict) else {}).get('stale_count', 0),
        'suggested_command': 'python scripts/project_os.py plan-recovery --root <project> --write-report',
        'policy': 'Generated recovery inspection summary only. It never replays, rolls back, deletes tmp files, removes locks, or rewrites canonical state.',
    }


def build_current_results_view(root: Path, result_rows: list[dict[str, str]]) -> dict[str, Any]:
    views = current_result_views(root, result_rows)
    audit = promotion_audit(root, result_rows)
    branch_counts = {branch_id: int(bucket.get('count', 0) or 0) for branch_id, bucket in views.get('branches', {}).items()}
    audit_warning_count = sum(
        len(audit.get(key, []) if isinstance(audit.get(key, []), list) else [])
        for key in ['missing_current_targets', 'cross_branch_promotions', 'unscoped_current_results', 'duplicate_current_targets']
    )
    return {
        'views': views,
        'audit': audit,
        'counts': {
            'all_current': int(views.get('all', {}).get('count', 0) or 0),
            'project_current': int(views.get('project', {}).get('count', 0) or 0),
            'branch_scope_count': len(branch_counts),
            'branch_current_total': sum(branch_counts.values()),
            'audit_warning_count': audit_warning_count,
            'audit_ok': bool(audit.get('ok')),
        },
        'branch_counts': branch_counts,
        'policy': 'Generated current-result and promotion-audit view only. It is derived from results.tsv plus current/ targets and must not be edited as state.',
    }


def dashboard_payload(ctx: Any, root: Path, recent_events: int = 20) -> dict[str, Any]:
    idx = ctx.indexes_dir(root)
    rows = {
        'branches': ctx.read_tsv(idx / 'branches.tsv'),
        'tasks': ctx.read_tsv(idx / 'tasks.tsv'),
        'runs': ctx.read_tsv(idx / 'runs.tsv'),
        'results': ctx.read_tsv(idx / 'results.tsv'),
        'assets': ctx.read_tsv(idx / 'assets.tsv'),
        'asset_locations': ctx.read_tsv(idx / 'asset_locations.tsv'),
        'asset_usage': ctx.read_tsv(idx / 'asset_usage.tsv'),
        'releases': ctx.read_tsv(idx / 'releases.tsv'),
    }
    current = {
        'session': ctx.current_session(root) if hasattr(ctx, 'current_session') else '',
        'source': ctx.focus_payload(root).get('source') if hasattr(ctx, 'focus_payload') else 'global',
        'branch': ctx.current_pointer(root, 'current_branch'),
        'task': ctx.current_pointer(root, 'current_task'),
        'run': ctx.current_pointer(root, 'current_run'),
    }
    sessions = ctx.session_summary_for_dashboard(root) if hasattr(ctx, 'session_summary_for_dashboard') else {}
    session_focus = build_session_focus_view(sessions)
    session_cleanup = build_session_cleanup_view(ctx, root)
    hooks = build_hooks_view(ctx, root)
    recovery = build_recovery_view(root)
    current_results = build_current_results_view(root, rows['results'])
    branch_counts: dict[str, dict[str, int]] = {}
    for row in rows['branches']:
        branch_counts[row.get('branch_id', '')] = {'tasks': 0, 'runs': 0, 'results': 0}
    for name in ['tasks', 'runs', 'results']:
        for row in rows[name]:
            b_id = row.get('branch_id', '')
            branch_counts.setdefault(b_id, {'tasks': 0, 'runs': 0, 'results': 0})
            branch_counts[b_id][name] += 1
    result_status_counts: dict[str, int] = {}
    run_status_counts: dict[str, int] = {}
    task_status_counts: dict[str, int] = {}
    for row in rows['results']:
        status = row.get('status', '') or '(blank)'
        result_status_counts[status] = result_status_counts.get(status, 0) + 1
    for row in rows['runs']:
        status = row.get('status', '') or '(blank)'
        run_status_counts[status] = run_status_counts.get(status, 0) + 1
    for row in rows['tasks']:
        status = row.get('status', '') or '(blank)'
        task_status_counts[status] = task_status_counts.get(status, 0) + 1
    return {
        'generated_at': ctx.now_iso(),
        'root': root.as_posix(),
        'project': ctx.read_json(ctx.project_os(root) / 'project.json') if (ctx.project_os(root) / 'project.json').exists() else {},
        'current': current,
        'sessions': sessions,
        'session_focus': session_focus,
        'session_cleanup': session_cleanup,
        'hooks': hooks,
        'recovery': recovery,
        'current_results': current_results,
        'counts': {key: len(value) for key, value in rows.items()},
        'status_counts': {
            'tasks': task_status_counts,
            'runs': run_status_counts,
            'results': result_status_counts,
        },
        'branch_counts': branch_counts,
        'indexes': rows,
        'graph': build_graph(rows, sessions),
        'recent_events': read_recent_events(ctx, root, recent_events),
        'policy': 'Generated dashboard/export view only. Canonical state remains .project_os/indexes/*.tsv, project.json, events.jsonl, and run/task/result manifests.',
    }


def html_table(title: str, rows: list[dict[str, str]], columns: list[str] | None = None, limit: int = 200) -> str:
    columns = columns or (list(rows[0].keys()) if rows else [])
    out = [f'<h2>{html.escape(title)}</h2>']
    if not rows:
        out.append('<p class="muted">No rows.</p>')
        return '\n'.join(out)
    if len(rows) > limit:
        out.append(f'<p class="muted">Showing first {limit} of {len(rows)} rows.</p>')
    out.append('<div class="table-wrap"><table>')
    out.append('<thead><tr>' + ''.join(f'<th>{html.escape(col)}</th>' for col in columns) + '</tr></thead>')
    out.append('<tbody>')
    for row in rows[:limit]:
        out.append('<tr>' + ''.join(f'<td>{html.escape(str(row.get(col, "")))}</td>' for col in columns) + '</tr>')
    out.append('</tbody></table></div>')
    return '\n'.join(out)


def dashboard_html(ctx: Any, payload: dict[str, Any]) -> str:
    counts = payload.get('counts', {})
    current = payload.get('current', {})
    status_counts = payload.get('status_counts', {})
    branch_counts = payload.get('branch_counts', {})
    indexes = payload.get('indexes', {})
    cards = ''.join(f'<div class="card"><div class="num">{html.escape(str(value))}</div><div>{html.escape(key)}</div></div>' for key, value in counts.items())
    branch_rows = [{'branch_id': key, **value} for key, value in sorted(branch_counts.items())]
    graph = payload.get('graph', {})
    graph_counts = graph.get('counts', {})
    graph_nodes = graph.get('nodes', [])
    graph_edges = graph.get('edges', [])
    session_focus = payload.get('session_focus', {}) if isinstance(payload.get('session_focus', {}), dict) else {}
    session_cleanup = payload.get('session_cleanup', {}) if isinstance(payload.get('session_cleanup', {}), dict) else {}
    hooks = payload.get('hooks', {}) if isinstance(payload.get('hooks', {}), dict) else {}
    recovery = payload.get('recovery', {}) if isinstance(payload.get('recovery', {}), dict) else {}
    current_results = payload.get('current_results', {}) if isinstance(payload.get('current_results', {}), dict) else {}
    status_rows: list[dict[str, str]] = []
    for group, values in status_counts.items():
        for status, count in sorted(values.items()):
            status_rows.append({'group': group, 'status': status, 'count': str(count)})
    event_rows = []
    for event in payload.get('recent_events', []):
        event_rows.append({
            'ts': str(event.get('ts', '')),
            'event': str(event.get('event', '')),
            'branch_id': str(event.get('branch_id', '')),
            'task_id': str(event.get('task_id', '')),
            'run_id': str(event.get('run_id', '')),
            'result_id': str(event.get('result_id', '')),
        })
    session_rows = payload.get('sessions', {}).get('sessions', []) if isinstance(payload.get('sessions', {}), dict) else []
    session_cards = ''.join(
        f'<div class="card"><div class="num">{html.escape(str(value))}</div><div>{html.escape(label)}</div></div>'
        for label, value in [
            ('sessions', session_focus.get('count', 0)),
            ('active', session_focus.get('active_count', 0)),
            ('paused', session_focus.get('paused_count', 0)),
            ('closed', session_focus.get('closed_count', 0)),
        ]
    )
    session_status_rows = [{'status': key, 'count': str(value)} for key, value in sorted((session_focus.get('status_counts') or {}).items())]
    session_cleanup_rows = []
    for item in session_cleanup.get('candidates', []) if isinstance(session_cleanup.get('candidates', []), list) else []:
        session_cleanup_rows.append({
            'session_id': str(item.get('session_id', '')),
            'status': str(item.get('status', '')),
            'age_days': str(item.get('age_days', '')),
            'session_dir': str(item.get('session_dir', '')),
            'current_branch': str((item.get('focus') or {}).get('current_branch', '')),
            'current_task': str((item.get('focus') or {}).get('current_task', '')),
            'current_run': str((item.get('focus') or {}).get('current_run', '')),
        })
    known_hook_kinds = set(hooks.get('known_kinds', []) if isinstance(hooks.get('known_kinds', []), list) else [])
    hook_kind_rows = [
        {'kind': str(kind), 'known': str(str(kind) in known_hook_kinds)}
        for kind in hooks.get('allowed_kinds', []) if isinstance(hooks.get('allowed_kinds', []), list)
    ]
    hook_status_rows = [
        {'key': key, 'value': str(hooks.get(key, ''))}
        for key in [
            'active_dispatcher_enabled',
            'manual_dispatcher_available',
            'config_exists',
            'config_requests_active_dispatcher',
            'event_source',
            'event_source_exists',
            'event_count',
            'malformed_event_count',
            'latest_event',
            'generated_report_count',
            'suggested_status_command',
            'suggested_report_command',
        ]
    ]
    recovery_summary = recovery.get('summary', {}) if isinstance(recovery.get('summary', {}), dict) else {}
    recovery_rows = [{'key': key, 'value': str(value)} for key, value in sorted(recovery_summary.items())]
    current_result_rows = []
    current_views = current_results.get('views', {}) if isinstance(current_results.get('views', {}), dict) else {}
    for item in (current_views.get('all', {}) if isinstance(current_views.get('all', {}), dict) else {}).get('results', []):
        if not isinstance(item, dict):
            continue
        current_result_rows.append({
            'result_id': str(item.get('result_id', '')),
            'status': str(item.get('status', '')),
            'branch_id': str(item.get('branch_id', '')),
            'task_id': str(item.get('task_id', '')),
            'run_id': str(item.get('run_id', '')),
            'type': str(item.get('type', '')),
            'path': str(item.get('path', '')),
            'targets': ', '.join(str(target) for target in item.get('current_targets', []) if target),
        })
    current_branch_count_rows = [
        {'branch_id': str(branch_id), 'current_results': str(count)}
        for branch_id, count in sorted((current_results.get('branch_counts') or {}).items())
    ] if isinstance(current_results.get('branch_counts'), dict) else []
    audit = current_results.get('audit', {}) if isinstance(current_results.get('audit', {}), dict) else {}
    promotion_audit_rows = []
    for kind in ['missing_current_targets', 'cross_branch_promotions', 'unscoped_current_results', 'duplicate_current_targets']:
        for item in audit.get(kind, []) if isinstance(audit.get(kind, []), list) else []:
            if not isinstance(item, dict):
                continue
            promotion_audit_rows.append({
                'kind': kind,
                'result_id': str(item.get('result_id', '')),
                'branch_id': str(item.get('branch_id', '')),
                'target': str(item.get('target', '')),
                'result_ids': ', '.join(str(value) for value in item.get('result_ids', []) if value) if isinstance(item.get('result_ids', []), list) else str(item.get('result_ids', '')),
            })
    current_count_rows = [
        {'key': key, 'value': str(value)}
        for key, value in sorted((current_results.get('counts') or {}).items())
    ] if isinstance(current_results.get('counts'), dict) else []
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>research-project-os dashboard</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; color: #172033; background: #f7f8fb; }}
    h1, h2 {{ color: #111827; }}
    .muted {{ color: #6b7280; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.75rem; margin: 1rem 0; }}
    .card {{ background: white; border: 1px solid #e5e7eb; border-radius: 0.75rem; padding: 1rem; box-shadow: 0 1px 2px rgba(0,0,0,.04); }}
    .num {{ font-size: 1.75rem; font-weight: 700; }}
    code {{ background: #eef2ff; padding: 0.1rem 0.25rem; border-radius: 0.25rem; }}
    .table-wrap {{ overflow-x: auto; background: white; border: 1px solid #e5e7eb; border-radius: 0.75rem; margin-bottom: 1.5rem; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; }}
    th, td {{ border-bottom: 1px solid #edf0f5; padding: 0.45rem 0.55rem; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; position: sticky; top: 0; }}
  </style>
</head>
<body>
  <h1>research-project-os dashboard</h1>
  <p class="muted">Generated at {html.escape(str(payload.get('generated_at', '')))}. This is a generated view; canonical state remains under <code>.project_os/</code>.</p>
  <h2>Current focus</h2>
  <ul>
    <li>session: <code>{html.escape(str(current.get('session', '')))}</code></li>
    <li>source: <code>{html.escape(str(current.get('source', 'global')))}</code></li>
    <li>branch: <code>{html.escape(str(current.get('branch', '')))}</code></li>
    <li>task: <code>{html.escape(str(current.get('task', '')))}</code></li>
    <li>run: <code>{html.escape(str(current.get('run', '')))}</code></li>
  </ul>
  <h2>Counts</h2>
  <div class="grid">{cards}</div>
  <h2>Current results and promotion audit</h2>
  <p class="muted">{html.escape(str(current_results.get('policy', 'Generated current-result view only.')))}</p>
  {html_table('Current result counts', current_count_rows, ['key', 'value'])}
  {html_table('Current results', current_result_rows, ['result_id', 'status', 'branch_id', 'task_id', 'run_id', 'type', 'path', 'targets'])}
  {html_table('Current results by branch', current_branch_count_rows, ['branch_id', 'current_results'])}
  {html_table('Promotion audit warnings', promotion_audit_rows, ['kind', 'result_id', 'branch_id', 'target', 'result_ids'])}
  <h2>Graph summary</h2>
  <p class="muted">Derived task/run/result graph; canonical state remains the indexes and manifests.</p>
  <div class="grid"><div class="card"><div class="num">{html.escape(str(graph_counts.get('nodes', 0)))}</div><div>graph nodes</div></div><div class="card"><div class="num">{html.escape(str(graph_counts.get('edges', 0)))}</div><div>graph edges</div></div></div>
  {html_table('Graph nodes', graph_nodes, ['id', 'kind', 'label', 'status', 'stage', 'type', 'path'], limit=300)}
  {html_table('Graph edges', graph_edges, ['source', 'target', 'relation', 'task_id', 'result_id', 'usage_kind'], limit=500)}
  <h2>Session focus</h2>
  <p class="muted">{html.escape(str(session_focus.get('policy', 'Generated session view only.')))}</p>
  <div class="grid">{session_cards}</div>
  <ul>
    <li>current session: <code>{html.escape(str(session_focus.get('current_session', '')))}</code></li>
    <li>stale current session: <code>{html.escape(str(session_focus.get('stale_current_session', False)))}</code></li>
  </ul>
  {html_table('Session status counts', session_status_rows, ['status', 'count'])}
  {html_table('Sessions', session_rows, ['session_id', 'status', 'is_current', 'current_branch', 'current_task', 'current_run', 'updated_at', 'notes'])}
  <h2>Session cleanup candidates</h2>
  <p class="muted">{html.escape(str(session_cleanup.get('policy', 'Generated cleanup view only.')))}</p>
  <p class="muted">closed-session candidates: {html.escape(str(session_cleanup.get('candidate_count', 0)))}; suggested review command: <code>{html.escape(str(session_cleanup.get('suggested_command', '')))}</code></p>
  {html_table('Session cleanup candidates', session_cleanup_rows, ['session_id', 'status', 'age_days', 'session_dir', 'current_branch', 'current_task', 'current_run'])}
  <h2>Hooks status</h2>
  <p class="muted">{html.escape(str(hooks.get('policy', 'Generated hooks view only.')))}</p>
  <p class="muted">Automatic hooks enabled: <code>{html.escape(str(hooks.get('active_dispatcher_enabled', False)))}</code>; manual dispatcher available: <code>{html.escape(str(hooks.get('manual_dispatcher_available', False)))}</code>.</p>
  {html_table('Hook status', hook_status_rows, ['key', 'value'])}
  {html_table('Allowed hook kinds', hook_kind_rows, ['kind', 'known'])}
  <h2>Recovery inspection</h2>
  <p class="muted">{html.escape(str(recovery.get('policy', 'Generated recovery view only.')))}</p>
  <p class="muted">suggested review command: <code>{html.escape(str(recovery.get('suggested_command', '')))}</code></p>
  {html_table('Recovery summary', recovery_rows, ['key', 'value'])}
  {html_table('Branch counts', branch_rows, ['branch_id', 'tasks', 'runs', 'results'])}
  {html_table('Status counts', status_rows, ['group', 'status', 'count'])}
  {html_table('Branches', indexes.get('branches', []), ctx.INDEX_HEADERS['branches.tsv'])}
  {html_table('Tasks', indexes.get('tasks', []), ctx.INDEX_HEADERS['tasks.tsv'])}
  {html_table('Runs', indexes.get('runs', []), ctx.INDEX_HEADERS['runs.tsv'])}
  {html_table('Results', indexes.get('results', []), ctx.INDEX_HEADERS['results.tsv'])}
  {html_table('Assets', indexes.get('assets', []), ctx.INDEX_HEADERS['assets.tsv'])}
  {html_table('Asset locations', indexes.get('asset_locations', []), ctx.INDEX_HEADERS['asset_locations.tsv'])}
  {html_table('Releases', indexes.get('releases', []), ctx.INDEX_HEADERS['releases.tsv'])}
  {html_table('Recent events', event_rows, ['ts', 'event', 'branch_id', 'task_id', 'run_id', 'result_id'])}
</body>
</html>
'''


def write_dashboard_sqlite(ctx: Any, path: Path, payload: dict[str, Any]) -> None:
    index_headers = {
        'branches': ctx.INDEX_HEADERS['branches.tsv'],
        'tasks': ctx.INDEX_HEADERS['tasks.tsv'],
        'runs': ctx.INDEX_HEADERS['runs.tsv'],
        'results': ctx.INDEX_HEADERS['results.tsv'],
        'assets': ctx.INDEX_HEADERS['assets.tsv'],
        'asset_locations': ctx.INDEX_HEADERS['asset_locations.tsv'],
        'asset_usage': ctx.INDEX_HEADERS['asset_usage.tsv'],
        'releases': ctx.INDEX_HEADERS['releases.tsv'],
    }
    tmp = path.with_suffix(path.suffix + '.tmp')
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp.as_posix())
    try:
        cur = conn.cursor()
        cur.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)')
        for key in ['generated_at', 'root', 'policy']:
            cur.execute('INSERT INTO meta(key, value) VALUES (?, ?)', (key, str(payload.get(key, ''))))
        for index_name, rows in payload.get('indexes', {}).items():
            table = re.sub(r'[^a-zA-Z0-9_]', '_', index_name)
            columns = list(index_headers.get(index_name, []))
            if not columns and rows:
                columns = list(rows[0].keys())
            if not columns:
                columns = ['id']
            cur.execute(f'DROP TABLE IF EXISTS {table}')
            cur.execute(f'CREATE TABLE {table} (' + ', '.join(f'"{col}" TEXT' for col in columns) + ')')
            placeholders = ', '.join('?' for _ in columns)
            quoted_cols = ', '.join(f'"{col}"' for col in columns)
            for row in rows:
                cur.execute(f'INSERT INTO {table} ({quoted_cols}) VALUES ({placeholders})', [str(row.get(col, '')) for col in columns])
        cur.execute('CREATE TABLE recent_events (ts TEXT, event TEXT, branch_id TEXT, task_id TEXT, run_id TEXT, result_id TEXT, detail_json TEXT)')
        for event in payload.get('recent_events', []):
            cur.execute('INSERT INTO recent_events VALUES (?, ?, ?, ?, ?, ?, ?)', (
                str(event.get('ts', '')), str(event.get('event', '')), str(event.get('branch_id', '')), str(event.get('task_id', '')),
                str(event.get('run_id', '')), str(event.get('result_id', '')), json.dumps(event.get('detail', {}), ensure_ascii=False),
            ))
        cur.execute('CREATE TABLE graph_nodes (id TEXT PRIMARY KEY, kind TEXT, label TEXT, attrs_json TEXT)')
        for node in payload.get('graph', {}).get('nodes', []):
            cur.execute('INSERT OR REPLACE INTO graph_nodes VALUES (?, ?, ?, ?)', (
                str(node.get('id', '')), str(node.get('kind', '')), str(node.get('label', '')), json.dumps(node, ensure_ascii=False),
            ))
        cur.execute('CREATE TABLE graph_edges (source TEXT, target TEXT, relation TEXT, attrs_json TEXT)')
        for edge in payload.get('graph', {}).get('edges', []):
            cur.execute('INSERT INTO graph_edges VALUES (?, ?, ?, ?)', (
                str(edge.get('source', '')), str(edge.get('target', '')), str(edge.get('relation', '')), json.dumps(edge, ensure_ascii=False),
            ))
        cur.execute('CREATE TABLE session_focus (key TEXT PRIMARY KEY, value TEXT)')
        session_focus = payload.get('session_focus', {}) if isinstance(payload.get('session_focus', {}), dict) else {}
        for key, value in session_focus.items():
            cur.execute('INSERT OR REPLACE INTO session_focus VALUES (?, ?)', (
                str(key),
                json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, bool)) else str(value),
            ))
        cur.execute('CREATE TABLE sessions (session_id TEXT PRIMARY KEY, status TEXT, is_current TEXT, current_branch TEXT, current_task TEXT, current_run TEXT, updated_at TEXT, notes TEXT, attrs_json TEXT)')
        session_rows = payload.get('sessions', {}).get('sessions', []) if isinstance(payload.get('sessions', {}), dict) else []
        for session in session_rows:
            cur.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (
                str(session.get('session_id', '')),
                str(session.get('status', '')),
                str(session.get('is_current', '')),
                str(session.get('current_branch', '')),
                str(session.get('current_task', '')),
                str(session.get('current_run', '')),
                str(session.get('updated_at', '')),
                str(session.get('notes', '')),
                json.dumps(session, ensure_ascii=False),
            ))
        cur.execute('CREATE TABLE session_cleanup_candidates (session_id TEXT PRIMARY KEY, status TEXT, age_days TEXT, session_dir TEXT, current_branch TEXT, current_task TEXT, current_run TEXT, attrs_json TEXT)')
        session_cleanup = payload.get('session_cleanup', {}) if isinstance(payload.get('session_cleanup', {}), dict) else {}
        for item in session_cleanup.get('candidates', []) if isinstance(session_cleanup.get('candidates', []), list) else []:
            focus = item.get('focus') if isinstance(item.get('focus'), dict) else {}
            cur.execute('INSERT OR REPLACE INTO session_cleanup_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (
                str(item.get('session_id', '')),
                str(item.get('status', '')),
                str(item.get('age_days', '')),
                str(item.get('session_dir', '')),
                str(focus.get('current_branch', '')),
                str(focus.get('current_task', '')),
                str(focus.get('current_run', '')),
                json.dumps(item, ensure_ascii=False),
            ))
        cur.execute('CREATE TABLE hooks_status (key TEXT PRIMARY KEY, value TEXT)')
        hooks = payload.get('hooks', {}) if isinstance(payload.get('hooks', {}), dict) else {}
        for key, value in hooks.items():
            cur.execute('INSERT OR REPLACE INTO hooks_status VALUES (?, ?)', (
                str(key),
                json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, bool)) else str(value),
            ))
        cur.execute('CREATE TABLE hooks_allowed_kinds (kind TEXT PRIMARY KEY, known TEXT)')
        known_hook_kinds = set(hooks.get('known_kinds', []) if isinstance(hooks.get('known_kinds', []), list) else [])
        for kind in hooks.get('allowed_kinds', []) if isinstance(hooks.get('allowed_kinds', []), list) else []:
            cur.execute('INSERT OR REPLACE INTO hooks_allowed_kinds VALUES (?, ?)', (str(kind), str(str(kind) in known_hook_kinds)))
        cur.execute('CREATE TABLE recovery_status (key TEXT PRIMARY KEY, value TEXT)')
        recovery = payload.get('recovery', {}) if isinstance(payload.get('recovery', {}), dict) else {}
        for key, value in recovery.items():
            cur.execute('INSERT OR REPLACE INTO recovery_status VALUES (?, ?)', (
                str(key),
                json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, bool)) else str(value),
            ))
        cur.execute('CREATE TABLE recovery_summary (key TEXT PRIMARY KEY, value TEXT)')
        recovery_summary = recovery.get('summary', {}) if isinstance(recovery.get('summary', {}), dict) else {}
        for key, value in recovery_summary.items():
            cur.execute('INSERT OR REPLACE INTO recovery_summary VALUES (?, ?)', (str(key), str(value)))
        current_results = payload.get('current_results', {}) if isinstance(payload.get('current_results', {}), dict) else {}
        cur.execute('CREATE TABLE current_results_status (key TEXT PRIMARY KEY, value TEXT)')
        for key, value in current_results.items():
            if key in {'views', 'audit'}:
                continue
            cur.execute('INSERT OR REPLACE INTO current_results_status VALUES (?, ?)', (
                str(key),
                json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, bool)) else str(value),
            ))
        current_views = current_results.get('views', {}) if isinstance(current_results.get('views', {}), dict) else {}
        cur.execute('CREATE TABLE current_results (result_id TEXT, scope TEXT, branch_scope TEXT, status TEXT, branch_id TEXT, task_id TEXT, run_id TEXT, type TEXT, path TEXT, targets TEXT, attrs_json TEXT)')
        inserted_current_keys: set[tuple[str, str, str]] = set()

        def insert_current_result(row: dict[str, Any], scope: str, branch_scope: str = '') -> None:
            result_id = str(row.get('result_id', ''))
            key = (result_id, scope, branch_scope)
            if not result_id or key in inserted_current_keys:
                return
            inserted_current_keys.add(key)
            targets = ','.join(str(target) for target in row.get('current_targets', []) if target) if isinstance(row.get('current_targets', []), list) else str(row.get('promoted_to', ''))
            cur.execute('INSERT INTO current_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (
                result_id,
                scope,
                branch_scope,
                str(row.get('status', '')),
                str(row.get('branch_id', '')),
                str(row.get('task_id', '')),
                str(row.get('run_id', '')),
                str(row.get('type', '')),
                str(row.get('path', '')),
                targets,
                json.dumps(row, ensure_ascii=False),
            ))

        for row in (current_views.get('all', {}) if isinstance(current_views.get('all', {}), dict) else {}).get('results', []):
            if isinstance(row, dict):
                insert_current_result(row, 'all')
        for row in (current_views.get('project', {}) if isinstance(current_views.get('project', {}), dict) else {}).get('results', []):
            if isinstance(row, dict):
                insert_current_result(row, 'project')
        branches_view = current_views.get('branches', {}) if isinstance(current_views.get('branches', {}), dict) else {}
        for branch_id, bucket in branches_view.items():
            for row in (bucket.get('results', []) if isinstance(bucket, dict) else []):
                if isinstance(row, dict):
                    insert_current_result(row, 'branch', str(branch_id))
        cur.execute('CREATE TABLE current_result_branch_counts (branch_id TEXT PRIMARY KEY, current_results TEXT)')
        branch_counts = current_results.get('branch_counts', {}) if isinstance(current_results.get('branch_counts', {}), dict) else {}
        for branch_id, count in branch_counts.items():
            cur.execute('INSERT OR REPLACE INTO current_result_branch_counts VALUES (?, ?)', (str(branch_id), str(count)))
        cur.execute('CREATE TABLE promotion_audit (kind TEXT, result_id TEXT, branch_id TEXT, target TEXT, result_ids TEXT, attrs_json TEXT)')
        audit = current_results.get('audit', {}) if isinstance(current_results.get('audit', {}), dict) else {}
        for kind in ['missing_current_targets', 'cross_branch_promotions', 'unscoped_current_results', 'duplicate_current_targets']:
            for item in audit.get(kind, []) if isinstance(audit.get(kind, []), list) else []:
                if not isinstance(item, dict):
                    continue
                cur.execute('INSERT INTO promotion_audit VALUES (?, ?, ?, ?, ?, ?)', (
                    kind,
                    str(item.get('result_id', '')),
                    str(item.get('branch_id', '')),
                    str(item.get('target', '')),
                    ','.join(str(value) for value in item.get('result_ids', []) if value) if isinstance(item.get('result_ids', []), list) else str(item.get('result_ids', '')),
                    json.dumps(item, ensure_ascii=False),
                ))
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, path)


def command_export_dashboard(args: Any, ctx: Any) -> int:
    root = Path(args.root).resolve()
    ctx.ensure_initialized(root)
    out_dir_raw = args.output or '.project_os/exports'
    out_dir = Path(out_dir_raw).expanduser()
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    payload = dashboard_payload(ctx, root, recent_events=args.recent_events)
    planned = {
        'dashboard_json': ctx.relpath(root, out_dir / 'dashboard.json'),
        'dashboard_html': ctx.relpath(root, out_dir / 'dashboard.html'),
        'dashboard_sqlite': ctx.relpath(root, out_dir / 'dashboard.sqlite') if args.sqlite else '',
    }
    if not args.apply:
        ctx.print_json({'dry_run_export_dashboard': {'output_dir': ctx.relpath(root, out_dir), 'files': planned, 'counts': payload['counts'], 'apply_required': True, 'sqlite': bool(args.sqlite), 'policy': payload['policy']}})
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx.write_json(out_dir / 'dashboard.json', payload)
    (out_dir / 'dashboard.html').write_text(dashboard_html(ctx, payload), encoding='utf-8')
    if args.sqlite:
        write_dashboard_sqlite(ctx, out_dir / 'dashboard.sqlite', payload)
    ctx.append_event(root, 'export.created', branch_id=ctx.current_branch(root), detail={'kind': 'dashboard', 'path': ctx.relpath(root, out_dir), 'sqlite': bool(args.sqlite)})
    ctx.print_json({'exported_dashboard': planned, 'counts': payload['counts'], 'policy': payload['policy']})
    return 0
