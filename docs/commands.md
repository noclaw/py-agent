# Slash commands

In the REPL, a line starting with `/` is a command. Defined in `agent.commands`.

## Built-ins

| command | does |
|---|---|
| `/help` | list available commands |
| `/clear` | start a fresh conversation (and a fresh session) |
| `/tools` | list the available tools |
| `/model [provider/]model` | show or switch the model at runtime |
| `/mode <mode>` | show or set the [permission mode](permissions.md) |
| `/sessions` | list saved [sessions](sessions.md) for this directory |
| `/resume <id>` | resume a saved session |
| `/checkpoints` | list file-edit checkpoints (snapshots before each `write`/`edit`) |
| `/rewind [N]` | restore files to checkpoint `N`, or undo the last with no arg |
| `/skills` | list available [skills](skills.md) |
| `/skill:<name>` | invoke a skill directly |
| `/exit`, `/quit` | leave |

A command either handles itself (e.g. `/clear`) or returns a **prompt** that runs as the
next agent turn (markdown commands and `/skill:<name>` do this).

## Custom markdown commands

Like Claude Code's `.claude/commands/`, drop a markdown file at:

- `.pya/commands/<name>.md` — project (this directory), or
- `~/.pya/commands/<name>.md` — user (everywhere).

The filename is the command name, the body is a prompt template, and optional frontmatter
sets its `description` and `argument-hint`. Subdirectories namespace as `dir:name`.

```markdown
---
description: Review a file for bugs
argument-hint: <path>
---
Read $1 and review it for bugs and edge cases. Be concise.
```

Then `/review src/agent/loop.py` runs that prompt. Substitutions:

- `$ARGUMENTS` — everything after the command name
- `$1`, `$2`, … — individual whitespace-separated arguments

Precedence: built-ins win over custom commands; project commands override user commands.

## Adding built-in commands in code

`build_registry(cwd)` returns a `SlashRegistry`. A command is a `SlashCommand(name,
description, run, argument_hint=None)` where `run(ctx, args) -> CommandOutcome | None`.
`CommandContext` gives the command access to the live `console`, `history`, `tools`,
`permissions`, `model`, `session`/`store`, and `registry`; `CommandOutcome(prompt=...,
exit=...)` tells the REPL what to do next. See `agent/commands.py` for the built-ins as
worked examples.

## Commands vs skills

Commands are **user-invoked** (you type `/name`). [Skills](skills.md) are **model-aware**:
the model picks them up from their description and reads the full `SKILL.md` on demand.
Reach for a command when *you* want a shortcut; a skill when you want the *model* to know
how to do something when the situation arises.
