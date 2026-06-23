# py-agent

A readable Python port of the [Pi](https://pi.dev) coding agent. The **agent loop and
tools are written in Python** here; the **model layer** (30+ providers, OAuth, transports,
local models) is delegated to Pi's `pi-ai` through the
[`pi-py`](https://github.com/noclaw/pi-py) SDK's `PiModelClient`.

It's meant as an example implementation — small enough to read while learning Python, and
a clean starting point for personal-assistant / second-brain agents (swap the coding
toolset for your own).

> **Status:** working end to end — the full tool set (read/write/edit/bash/grep/find/ls),
> the agent loop, system prompt, interactive CLI/REPL, a **permissions** system and a
> **hooks** system (both modeled on Claude Code). Next: slash commands, sessions,
> compaction, memory tools. See [`PLAN.md`](PLAN.md).

## Architecture

```
┌──────────────────────── Python (this repo) ────────────────────────┐
│  cli / app / render                                                 │
│  loop  ──calls──>  tools (read/write/edit/bash/grep/find/ls)        │
│    │                                                                │
│    │ per turn: stream(context{system, messages, tools})            │
│    ▼                                                                │
│  pi_py_sdk.PiModelClient  ──JSONL──┐                                │
└─────────────────────────────────────┼──────────────────────────────┘
                                       ▼
              Node shim  ──imports──>  @earendil-works/pi-ai
              (providers, auth, transports, local models)
```

Only the LLM call crosses into Node; the loop and tools stay in readable Python. See
`PLAN.md` for the pi-agent-core vs pi-coding-agent module map this port follows.

## Requirements

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/) (recommended) or pip
- **Node** on `PATH` and a local `pi` install (provides the bundled `pi-ai`):
  ```bash
  npm i -g @earendil-works/pi-coding-agent
  ```
- Credentials: a provider env var (e.g. `ANTHROPIC_API_KEY`) **or** an existing Pi OAuth
  login (`pi`, then `/login`).

## Setup

```bash
uv sync --extra dev
```

This pulls `pi-py-sdk` from PyPI, so the repo is self-contained. (To develop against a
local pi-py checkout instead, add `[tool.uv.sources]` → `pi-py-sdk = { path = "../pi-py",
editable = true }` to `pyproject.toml`.)

## Try it

```bash
uv run pya --version
uv run pya models --provider anthropic        # list models (smoke-tests the pipeline)
uv run pya -p "What does this project do?"     # one-shot: run a prompt and exit
uv run pya                                      # interactive REPL (Ctrl-C aborts a turn, Ctrl-D quits)
uv run pya --cwd /path/to/project --model claude-sonnet-4-6
```

In the REPL, `/help` lists commands, `/clear` resets the conversation, `/exit` quits.
The agent streams its reply, shows each tool call (`› bash …`) and result (`✓`/`✗`), and
prints a token summary when the turn finishes.

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
`PostToolUse` can attach `additional_context` fed back to the model.

## Develop

```bash
uv run pytest                 # unit tests (no Node)
uv run pytest -m integration  # live tests (need Node + pi-ai)
```
