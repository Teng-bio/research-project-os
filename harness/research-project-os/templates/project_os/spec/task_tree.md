# Task tree

Tasks are branch-local workspaces with globally unique task IDs. Future DAG dependencies live in `task.json.depends_on`.

Use `update-task`, `update-task-stage`, `add-dependency`, `remove-dependency`, `add-context`, `remove-context`, `update-handoff`, and `close-task` for lifecycle/context updates.
