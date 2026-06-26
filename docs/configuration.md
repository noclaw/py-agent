# Configuration

py-agent favors flags and a small `.pya/` directory over a config file.

## CLI flags

```
pya [--model MODEL] [--provider PROVIDER] [--reasoning LEVEL] [--cwd DIR]
    [--permission-mode {default,acceptEdits,plan,bypass}] [--yolo]
    [-c/--continue] [--resume SESSION_ID] [--no-session]
    [--max-retries N] [--no-compact] [--context-window N] [--no-subagent]
    [-p/--print PROMPT]
pya models [--provider PROVIDER]
```

- `--model` / `--provider` — which model to use ([models & providers](models-and-providers.md)).
- `--reasoning` — thinking level (minimal…xhigh).
- `--cwd` — directory the agent operates in (tools, project context, skills/commands).
- `--permission-mode` / `--yolo` — tool gating ([permissions](permissions.md)).
- `-c` / `--resume` / `--no-session` — [sessions](sessions.md).
- `--max-retries` — retries for transient model errors per turn (default 2; `0` disables
  [auto-retry](agent-loop.md#auto-retry)).
- `--no-compact` / `--context-window` — disable, or size, [compaction](agent-loop.md#compaction)
  of old history (default on, window 200000 tokens).
- `--no-subagent` — don't expose the [`task` tool](tools.md#sub-agents-the-task-tool)
  (sub-agent delegation); it's on by default.
- `-p` — run one prompt and exit (otherwise a REPL).

The REPL also installs a default [`UserPromptSubmit` hook](hooks.md#the-default-hook) that
tags each prompt with the current git branch.

## Environment variables

| var | effect |
|---|---|
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` (etc.) | provider credentials (see [models & providers](models-and-providers.md)) |
| `PYA_SESSIONS_DIR` | where sessions are stored (default `~/.pya/sessions`) |
| `PYA_SETTINGS_FILE` | path to the settings file (default `~/.pya/settings.toml`) |

## The `.pya/` directory

Per-project under your working directory, and per-user under `~/.pya/`:

```
.pya/
  commands/<name>.md         # custom slash commands   (see commands.md)
  skills/<name>/SKILL.md     # skills                   (see skills.md)
  models.json                # custom/local models     (see models-and-providers.md)
```

Project entries (under `--cwd`) override user entries (`~/.pya/`) with the same name.
Sessions live under `~/.pya/sessions/` (or `PYA_SESSIONS_DIR`). User-level only:

```
~/.pya/
  settings.toml              # provider keys, enabled providers, model allowlist, default
                             #   (chmod 600 — holds API keys; see models-and-providers.md)
```

## Project context

If an `AGENTS.md` or `CLAUDE.md` exists in the working directory, its contents are included
in the system prompt as `<project_context>` automatically — a simple way to give the agent
standing instructions for a project.
