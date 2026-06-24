# Context manifest schema

`context_manifest.jsonl` controls what an agent should read for a task.

Each non-empty line is a JSON object:

```jsonl
{"type":"state","path":"PROJECT_STATE.md","purpose":"current status","required":true}
{"type":"workflow","path":".project_os/workflow.md","purpose":"phase rules","required":true}
{"type":"spec","path":"docs/CURRENT_PLAN.md","purpose":"authoritative plan","required":true}
{"type":"run","path":"runs/<branch_id>/<run_id>/RUN_MANIFEST.json","purpose":"provenance","required":false}
{"type":"result","path":"RESULTS_INDEX.md","purpose":"accepted outputs","required":false}
```

Required keys:

- `type`
- `path`
- `purpose`
- `required`

Paths should be project-root relative unless an external absolute path is unavoidable. Prefer adding external data/resources to `DATA_ASSETS.md` and referencing the registry entry.
