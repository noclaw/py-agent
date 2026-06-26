# Getting started

This is the detailed companion to the top-level [QUICKSTART](../QUICKSTART.md): the same
path to a first run, plus how to configure a provider, select a model, and install the CLI
for everyday use.

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

The model layer (providers, auth, transports, local models) is delegated to `pi-ai`
through the [`pi-py`](https://github.com/noclaw/pi-py) SDK — py-agent never talks to a
provider's HTTP API directly. See [models & providers](models-and-providers.md) and
[architecture](architecture.md).

## Install

**Developer flow (run from a clone):**

```bash
git clone https://github.com/noclaw/py-agent && cd py-agent
uv sync                 # runtime deps only
uv sync --extra dev     # add this if you'll run the tests
uv run pya --version
```

`uv run pya …` runs the CLI inside the project's virtualenv. Use this while editing the
agent itself.

**Install the CLI globally (run `pya` from anywhere):**

```bash
uv tool install .       # from the repo root
pya --version
```

This installs the `pya` executable to `~/.local/bin` (via uv's tool store). If that
directory isn't on your `PATH`, run `uv tool update-shell` once and restart your shell.
`pipx install .` is an equivalent alternative. To update after pulling new code, re-run
`uv tool install . --force`.

The rest of these docs write `pya`; under the developer flow, prefix with `uv run`.

## Configure a provider

Credentials are resolved by `pi-ai`/the shim, not by py-agent — there's nothing to put in
a config file. The resolution order is:

1. an explicit key passed in code (rarely needed),
2. the provider's **environment variable**, or
3. an existing Pi **OAuth login** in `~/.pi/agent/auth.json`.

So pick whichever fits:

```bash
# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
export OPENAI_API_KEY=sk-...

# …or reuse a Pi login (no env var needed)
pi          # then type /login once; py-agent refreshes the token automatically
```

Other providers follow the same pattern (`GEMINI_API_KEY`, `GROQ_API_KEY`, …). `pya
models` lists every provider `pi-ai` knows about.

## Select a model

```bash
pya models                              # list everything pi-ai knows about
pya models --provider anthropic         # filter to one provider
pya --provider anthropic --model claude-sonnet-4-6 -p "hello"
pya --provider openai    --model gpt-5.1            -p "hello"
```

In the REPL, switch at runtime:

```
/model claude-opus-4-8
/model openai/gpt-5.1
```

Defaults are `anthropic` / `claude-sonnet-4-6`, set in `src/agent/config.py`
(`DEFAULT_PROVIDER`, `DEFAULT_MODEL`). `--reasoning {minimal,low,medium,high,xhigh}` sets
the thinking level for models that support it. For self-hosted / local models, see
[models & providers › local & custom models](models-and-providers.md#local--custom-models).

## First run

```bash
pya models --provider anthropic     # lists models — smoke-tests the whole pipeline
pya -p "Summarize what this repo does"   # one-shot
pya                                       # interactive REPL
```

In the REPL, type a message to start. The agent streams its reply and shows each tool call
(`› bash …`) with a `✓`/`✗` result. Mutating tools ask for approval (answer `y`/`a`/`n`) —
see [permissions](permissions.md). `/help` lists commands; Ctrl-C interrupts the current
turn; Ctrl-D quits.

```bash
pya --cwd /path/to/project --model claude-sonnet-4-6
pya -c                # continue the most recent conversation here
pya --yolo            # skip approval prompts (allow everything)
```

## Troubleshooting

- **`pya: command not found`** after `uv tool install` — `~/.local/bin` isn't on `PATH`.
  Run `uv tool update-shell` and restart the shell (or use the `uv run pya` flow).
- **`models` hangs, returns nothing, or a Node error** — Node isn't on `PATH`, or
  `pi`/`pi-ai` isn't installed. Check `node --version` and `pi --version`; re-run
  `npm i -g @earendil-works/pi-coding-agent`. If pi-ai lives somewhere unusual, set
  `PI_AI_DIR=/path/to/@earendil-works/pi-ai`; if Node isn't `node` on `PATH`, set
  `PI_NODE`.
- **Auth / 401 errors mid-turn** — the provider key isn't set, or an OAuth token expired.
  Set the env var, or re-run `pi` → `/login`.
- **The agent edits the wrong files** — pass `--cwd` to point it at the right project.

## What to read next

- [Configuration](configuration.md) — flags, env vars, and the `.pya/` layout.
- [Models & providers](models-and-providers.md) — credentials, switching, local models.
- [Tutorials](tutorials/README.md) — understand how the agent works, part by part.
- [Building your own agent](building-your-own-agent.md) — drive the loop programmatically.
