# py-agent

A readable Python port of the [Pi](https://pi.dev) coding agent. The **agent loop and
tools are written in Python** here; the **model layer** (30+ providers, OAuth, transports,
local models) is delegated to Pi's `pi-ai` through the
[`pi-py`](https://github.com/noclaw/pi-py) SDK's `PiModelClient`.

It's meant as an example implementation — small enough to read while learning Python, and
a clean starting point for personal-assistant / second-brain agents (swap the coding
toolset for your own).

> **Status:** working end to end — message types, the default tools (read/write/edit/bash),
> the agent loop, the system prompt, and the interactive CLI/REPL are implemented and
> tested. Optional features (sessions, compaction, permissions, slash/memory commands)
> are next. See [`PLAN.md`](PLAN.md).

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

`pi-py-sdk` 0.2.0 isn't on PyPI yet, so it's wired as a local path dependency to
`../pi-py` (see `[tool.uv.sources]` in `pyproject.toml`). Clone both repos side by side.

```bash
uv sync --extra dev
```

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

## Develop

```bash
uv run pytest                 # unit tests (no Node)
uv run pytest -m integration  # live tests (need Node + pi-ai)
```
