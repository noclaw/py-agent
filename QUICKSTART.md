# Quickstart

Get py-agent running in a few minutes — install, point it at a model, and start a turn.
For the full tour see the [README](README.md); for depth see [`docs/`](docs/README.md).

## 1. Prerequisites

- **Python ≥ 3.11** and [`uv`](https://docs.astral.sh/uv/) (recommended) — or pip. No Node.
- **Credentials** — either of:
  - a provider API key in your environment (e.g. `export ANTHROPIC_API_KEY=...` or
    `export OPENAI_API_KEY=...`), **or**
  - for Claude Pro/Max, an OAuth login at `~/.pi/agent/auth.json` (run `pi`, then `/login`
    once — that's the only thing that needs Node, and only for the login, not at runtime).

## 2. Install

**Try it from a clone (developer flow):**

```bash
git clone https://github.com/noclaw/py-agent && cd py-agent
uv sync                       # create the venv and install deps
uv run pya --version          # runs the CLI inside the project venv
```

**Install the CLI so `pya` runs from anywhere:**

```bash
uv tool install .             # from the repo root — installs the `pya` executable
pya --version
```

`uv tool install` puts `pya` on your `PATH` (via `~/.local/bin`); if that directory isn't
on your `PATH`, run `uv tool update-shell` once. (Prefer pipx? `pipx install .` works too.)
The rest of this guide writes `pya`; if you used the clone flow, prefix commands with
`uv run` (i.e. `uv run pya …`).

## 3. First run

```bash
pya models --provider anthropic        # list models — also smoke-tests the whole pipeline
pya -p "Summarize what this repo does"  # one-shot: run a prompt and exit
pya                                      # interactive REPL
```

In the REPL, type a message to start. The agent streams its reply and shows each tool call
(`› bash …`) with a `✓`/`✗` result. Mutating tools (`write`/`edit`/`bash`) ask for approval
— answer `y` (once), `a` (always, for the session), or `n`. `/help` lists commands; Ctrl-C
interrupts the current turn; Ctrl-D quits.

## 4. Pick a provider and model

`pya` lists a curated built-in catalog (Anthropic + OpenAI) plus your custom models — run `pya models`.
Set credentials for the provider you want, then choose it:

```bash
# Anthropic (the default provider)
export ANTHROPIC_API_KEY=sk-ant-...
pya --provider anthropic --model claude-sonnet-4-6 -p "hello"

# OpenAI
export OPENAI_API_KEY=sk-...
pya --provider openai --model gpt-5.1 -p "hello"
```

In the REPL, switch at runtime with `/model`:

```
/model claude-opus-4-8
/model openai/gpt-5.1
```

The defaults (`anthropic` / `claude-sonnet-4-6`) live in `src/agent/config.py`. For
credential resolution order and local/self-hosted models, see
[models & providers](docs/models-and-providers.md).

## 5. Where things live

- **Sessions** — `~/.pya/sessions/<id>.jsonl` (override with `PYA_SESSIONS_DIR`).
  `pya -c` continues the last one for this directory.
- **Custom commands / skills** — `.pya/commands/` and `.pya/skills/` (per project) or
  `~/.pya/...` (per user). See [commands](docs/commands.md) / [skills](docs/skills.md).
- **Provider credentials** — your environment, or Pi's OAuth login at `~/.pi/agent/`.
  py-agent itself keeps no credentials.

## Troubleshooting

| symptom | fix |
|---|---|
| `pya: command not found` after `uv tool install` | `~/.local/bin` isn't on `PATH` — run `uv tool update-shell`, then restart the shell. |
| `models` shows nothing useful | Set a provider key (`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`) and pick that provider; add local models in `~/.pya/models.json`. |
| auth / 401 errors mid-turn | The provider key isn't set (or the Pro/Max OAuth login expired). Set the env var, or re-run `pi` → `/login`. |
| `rate_limit_error` (429) | Provider-side rate/usage limit — wait and retry, or use a different key/model. |
| wrong directory | `pya --cwd /path/to/project` sets where the agent reads/writes files. |

## Next

- [Getting started](docs/getting-started.md) — the same ground in more detail, plus configuration.
- [Models & providers](docs/models-and-providers.md) — credentials, switching, local models.
- [Tutorials](docs/tutorials/README.md) — build up an understanding of how the agent works.
