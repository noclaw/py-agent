# Getting started

## Requirements

- Python ≥ 3.11 and [`uv`](https://docs.astral.sh/uv/) (or pip).
- **Node** on `PATH` and a local `pi` install — it bundles `pi-ai`, which the model shim
  imports:
  ```bash
  npm i -g @earendil-works/pi-coding-agent
  ```
- Credentials (either one):
  - a provider API key in the environment, e.g. `export ANTHROPIC_API_KEY=...`, or
  - an existing Pi OAuth login — run `pi`, then `/login`. py-agent reads/refreshes the
    token from `~/.pi/agent/auth.json` automatically.

See [models & providers](models-and-providers.md) for how credentials resolve and how to
use other providers or local models.

## Install

```bash
git clone https://github.com/noclaw/py-agent && cd py-agent
uv sync --extra dev
```

## First run

```bash
uv run pya models --provider anthropic     # lists models — smoke-tests the whole pipeline
uv run pya -p "Summarize what this repo does"   # one-shot
uv run pya                                       # interactive REPL
```

In the REPL, type a message to start. The agent streams its reply and shows each tool call
(`› bash …`) with a `✓`/`✗` result. Mutating tools ask for approval (answer `y`/`a`/`n`) —
see [permissions](permissions.md). `/help` lists commands; Ctrl-C interrupts the current
turn; Ctrl-D quits.

```bash
uv run pya --cwd /path/to/project --model claude-sonnet-4-6
uv run pya -c                # continue the most recent conversation here
uv run pya --yolo            # skip approval prompts (allow everything)
```

## What to read next

- [Configuration](configuration.md) — env vars and the `.pya/` layout.
- [Building your own agent](building-your-own-agent.md) — use the loop programmatically.
