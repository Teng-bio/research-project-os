# Adapter policy

Core `.project_os/` files are platform-neutral.

## Codex

- Use the global/user skill as the operation entry point.
- Optional repo-scoped skills can live in `.agents/skills/`.
- Optional project agents/config can live in `.codex/` after the harness is stable.
- Codex memories are helpful recall, not canonical project truth.

## Claude Code

- A small `CLAUDE.md` or `.claude/skills` adapter may point to `.project_os/workflow.md` and runtime pointers.
- Do not duplicate task state into Claude-only files.

## OpenCode, Cursor, and other agents

- Generate only thin entry files that tell the agent to read `.project_os/workflow.md`, runtime pointers, and `context_manifest.jsonl`.
- Platform files are disposable adapters, not the source of truth.

## Plugins

Package as a Codex plugin only after the local skill and `.project_os/` templates pass real-project smoke tests.
