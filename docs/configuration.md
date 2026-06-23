# Configuration

py-agent favors flags and a small `.pya/` directory over a config file.

## CLI flags

```
pya [--model MODEL] [--provider PROVIDER] [--reasoning LEVEL] [--cwd DIR]
    [--permission-mode {default,acceptEdits,plan,bypass}] [--yolo]
    [-c/--continue] [--resume SESSION_ID] [--no-session]
    [-p/--print PROMPT]
pya models [--provider PROVIDER]
```

- `--model` / `--provider` — which model to use ([models & providers](models-and-providers.md)).
- `--reasoning` — thinking level (minimal…xhigh).
- `--cwd` — directory the agent operates in (tools, project context, skills/commands).
- `--permission-mode` / `--yolo` — tool gating ([permissions](permissions.md)).
- `-c` / `--resume` / `--no-session` — [sessions](sessions.md).
- `-p` — run one prompt and exit (otherwise a REPL).

## Environment variables

| var | effect |
|---|---|
| `ANTHROPIC_API_KEY` (etc.) | provider credentials (see [models & providers](models-and-providers.md)) |
| `PYA_SESSIONS_DIR` | where sessions are stored (default `~/.pya/sessions`) |
| `PI_AI_DIR` | path to the `@earendil-works/pi-ai` package, if it can't be found via the `pi` install |
| `PI_NODE` | path to the `node` executable, if not on `PATH` |

## The `.pya/` directory

Per-project under your working directory, and per-user under `~/.pya/`:

```
.pya/
  commands/<name>.md         # custom slash commands   (see commands.md)
  skills/<name>/SKILL.md     # skills                   (see skills.md)
```

Project entries (under `--cwd`) override user entries (`~/.pya/`) with the same name.
Sessions live under `~/.pya/sessions/` (or `PYA_SESSIONS_DIR`).

## Project context

If an `AGENTS.md` or `CLAUDE.md` exists in the working directory, its contents are included
in the system prompt as `<project_context>` automatically — a simple way to give the agent
standing instructions for a project.
