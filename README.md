# py-agent

A readable Python coding agent (originally ported from [Pi](https://pi.dev)). **All of it
is Python** — the agent loop, the tools, and the model layer, which talks directly to
provider HTTP APIs over `httpx`. No Node, no subprocess. It supports OpenAI-compatible
endpoints (OpenAI + local servers: Ollama, LM Studio, vLLM, …) and Anthropic.

It's meant as an example implementation — small enough to read while learning Python, and
a clean starting point for personal-assistant / second-brain agents (swap the coding
toolset for your own).

> **Status:** working end to end — the full tool set (read/write/edit/bash/grep/find/ls),
> the agent loop, system prompt, interactive CLI/REPL, **permissions**, **hooks**, **slash
> commands** with custom markdown commands, **skills**, **session** save/resume,
> **compaction**, **auto-retry**, **sub-agents** (a `task` tool), a **model picker**, and a
> **native provider layer** (OpenAI-compatible + Anthropic, no Node — see
> [`PROVIDERS.md`](PROVIDERS.md)). Next: memory / second-brain tools. See [`PLAN.md`](PLAN.md).

## Architecture

```
┌──────────────────────── Python (this repo) ────────────────────────┐
│  cli / app / render                                                 │
│  loop  ──calls──>  tools (read/write/edit/bash/grep/find/ls)        │
│    │                                                                │
│    │ per turn: stream(context{system, messages, tools})            │
│    ▼                                                                │
│  model ──routes by api──>  providers/                              │
│        openai_compat (OpenAI + local)   anthropic (Claude)         │
│              │                               │                      │
│              └────────── httpx ──────────────┘                      │
└─────────────────────────────────┼───────────────────────────────────┘
                                   ▼
                    provider HTTP APIs (SSE streaming)
```

Everything is in-process Python; the only thing that leaves is the HTTPS call to the
provider. To support a transport we don't ship, implement the small `Provider` protocol.

> **In a hurry?** The [QUICKSTART](QUICKSTART.md) gets you from zero to a first turn —
> install, credentials, pick a model. This README is the fuller tour.

## Requirements

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/) (recommended) or pip
- Credentials: a provider API key — an env var (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …)
  or `~/.pya/settings.toml` (no `export` needed; also scopes which providers/models the CLI
  offers). Local servers usually need none.

No Node and no `pi` install are required — anywhere.

## Setup

```bash
uv sync --extra dev
```

Pure-Python dependencies (`httpx`, `pydantic`, `rich`). To run `pya` from anywhere (not
just `uv run` inside the repo), install the CLI:

```bash
uv tool install .       # or: pipx install .
pya --version
```

## Try it

```bash
uv run pya --version
uv run pya models --provider anthropic        # list models (smoke-tests the pipeline)
uv run pya -p "What does this project do?"     # one-shot: run a prompt and exit
uv run pya                                      # interactive REPL (Ctrl-C aborts a turn, Ctrl-D quits)
uv run pya --cwd /path/to/project --model claude-sonnet-4-6
```

The agent streams its reply, shows each tool call (`› bash …`) and result (`✓`/`✗`), and
prints a token summary when the turn finishes.

## Slash commands

In the REPL, lines starting with `/` are commands. Built-ins:

| command | what it does |
|---|---|
| `/help` | list available commands |
| `/clear` | start a fresh conversation |
| `/tools` | list the available tools |
| `/model [[provider/]model]` | switch the model by id, or open a fuzzy picker with no arg |
| `/mode <mode>` | show or set the permission mode |
| `/sessions` | list saved sessions for this directory |
| `/resume <id>` | resume a saved session |
| `/skills` | list available skills (see below) |
| `/exit`, `/quit` | leave |

**Custom commands** are markdown files (just like Claude Code's `.claude/commands/`):
drop a file at `.pya/commands/<name>.md` (project) or `~/.pya/commands/<name>.md` (user).
The filename is the command, the body is a prompt template, and optional frontmatter sets
its `description`/`argument-hint`. `$ARGUMENTS` expands to all args; `$1`, `$2`, … to
positional ones. Subdirectories namespace as `dir:name`.

```markdown
---
description: Review a file for bugs
argument-hint: <path>
---
Read $1 and review it for bugs and edge cases. Be concise.
```

Then `/review src/agent/loop.py` runs that prompt as a turn.

## Skills

Skills teach the agent workflows/knowledge with plain markdown. Unlike slash commands
(user-invoked), skills are **model-aware** through *progressive disclosure*: only each
skill's name and description go into the system prompt, and the model reads the full
`SKILL.md` (with the `read` tool) when a task matches.

Create `.pya/skills/<name>/SKILL.md` (project) or `~/.pya/skills/<name>/SKILL.md` (user):

```markdown
---
name: changelog
description: Use when asked to update the changelog or summarize recent changes.
---
Read CHANGELOG.md, then add a new entry under "Unreleased" summarizing the latest
commits (`git log`). Keep entries terse and grouped by Added/Changed/Fixed.
```

The skill directory can hold helper files/scripts the instructions reference. `/skills`
lists them; `/skill:<name>` invokes one directly. Otherwise the model picks a skill up on
its own when your request matches its description.

## Sessions

Conversations are saved to `~/.pya/sessions/<id>.jsonl` (override with
`PYA_SESSIONS_DIR`), one per conversation, tagged with the working directory so resume is
per-project.

```bash
uv run pya -c                 # continue the most recent session for this directory
uv run pya --resume <id>      # resume a specific session
uv run pya --no-session       # don't save this conversation
```

It works one-shot too — `pya -c -p "..."` continues a prior conversation non-interactively.
In the REPL, `/sessions` lists them and `/resume <id>` loads one (and restores its model).

## Permissions

Mutating tools (`write`/`edit`/`bash`) are gated; read-only tools (`read`/`grep`/`find`/
`ls`) always run. Modes mirror Claude Code:

```bash
uv run pya                              # default: ask before each mutating tool
uv run pya --permission-mode acceptEdits  # auto-allow write/edit; still ask for bash
uv run pya --permission-mode plan         # read-only: deny all mutations
uv run pya --yolo                         # bypass: allow everything
```

At an approval prompt, answer `y` (once), `a` (always — remembers a rule for the
session), or `n` (deny). Rules can also be set up front, e.g. allow any `git` command and
never allow `rm`:

```python
from agent.permissions import Permissions
Permissions(allow=["bash(git *)"], deny=["bash(rm *)"])
```

## Hooks

Register callbacks at key points (`PreToolUse`, `PostToolUse`, `UserPromptSubmit`) — same
shapes as Claude Code, but as plain Python:

```python
from agent.hooks import Hooks, HookResult

hooks = Hooks()

@hooks.pre_tool_use(matcher="bash")
def block_force_push(event):
    if "push --force" in event.tool_input.get("command", ""):
        return HookResult(decision="deny", reason="no force pushes")

# pass to the loop:  run_agent(model, tools, history, hooks=hooks, ...)
```

A `PreToolUse` hook can `allow` (skip the permission check) or `deny` (block) a call;
`PostToolUse` can attach `additional_context` fed back to the model. In the REPL a default
`UserPromptSubmit` hook tags each prompt with the current git branch — pass your own
`Hooks()` to replace it.

## Sub-agents

The agent can delegate a self-contained sub-task to a child agent with its own tools and
turn budget via the `task` tool. The child runs autonomously and returns a single report,
so the parent's context stays clean of the child's intermediate steps — handy for
"scout → plan → implement" style work. It's on by default; disable with `--no-subagent`.
See [tools › sub-agents](docs/tools.md#sub-agents-the-task-tool).

## Compaction & auto-retry

Two reliability features keep longer runs healthy, both on by default:

```bash
uv run pya --no-compact            # disable auto-summarizing old history
uv run pya --context-window 400000 # size compaction to the model's window (default 200000)
uv run pya --max-retries 0         # disable retrying transient model errors (default 2)
```

**Compaction** summarizes the oldest turns once the conversation nears the context window;
**auto-retry** re-streams a turn that ends in a transient model error (exponential backoff).
Both are seams on the loop — see [the agent loop](docs/agent-loop.md#auto-retry).

## Documentation

Deeper guides live in [`docs/`](docs/README.md): [architecture](docs/architecture.md), the
[agent loop](docs/agent-loop.md), writing [tools](docs/tools.md) / [hooks](docs/hooks.md) /
[commands](docs/commands.md) / [skills](docs/skills.md), [permissions](docs/permissions.md),
[sessions](docs/sessions.md), [models & providers](docs/models-and-providers.md), and
[building your own agent](docs/building-your-own-agent.md).

## Develop

```bash
uv run pytest                 # unit tests (no Node)
uv run pytest -m integration  # live tests (need Node + pi-ai)
```

## License

[MIT](LICENSE).
