# Development

## Layout

```
src/agent/        the package (see architecture.md for the module map)
tests/            pytest; no network (a scripted fake model + httpx.MockTransport stand in)
docs/             these docs
PLAN.md           status + remaining optional phases
```

## Setup

```bash
uv sync --extra dev
```

Pure-Python dependencies (`httpx`, `pydantic`, `rich`) — the repo is self-contained, no
Node. (Reminder: virtualenvs aren't relocatable — if you move/rename the repo directory,
`rm -rf .venv && uv sync` to rebuild it.)

`uv run pya …` always runs the current source. If you also install the global CLI for
everyday use, install it **editable** so it tracks your edits:

```bash
uv tool install --editable . --force      # ~/.local/bin/pya now follows the source
```

A non-editable `uv tool install .` builds a wheel keyed by version (`0.0.1`); because the
version rarely changes, re-running it reinstalls the *cached* wheel and your edits don't show
up. Use the editable install above, or force a rebuild with
`uv cache clean py-agent && uv tool install . --reinstall`.

## Tests

```bash
uv run pytest                         # unit tests (no network; providers use httpx.MockTransport)
uv run pytest -m integration          # live tests, gated (need a real key)
PYA_LIVE_LLM=1 ANTHROPIC_API_KEY=… uv run pytest -m integration   # tests that call a model
```

Integration tests that call a model are gated by `PYA_LIVE_LLM=1` plus a real
`ANTHROPIC_API_KEY` (so the default `uv run pytest` never hits the network). They default to
a cheap model; override with `PYA_LIVE_MODEL` / `PYA_LIVE_PROVIDER`.

### The fake-model fixture

The most important test tool is `tests/fakes.py`: `FakeModel` replays scripted
`StreamEvent` turns, with `text_turn`, `tool_turn`, and `error_turn` builders. It lets the
loop, permissions, hooks, and commands be tested deterministically with no network. Prefer
it over live tests for logic; keep live tests few and high-signal.

## Conventions

- 4-space indent, type hints, `from __future__ import annotations`, Google-ish docstrings.
- Async-first; provide a sync facade only where it helps the CLI.
- Internal data uses dataclasses; Pydantic is reserved for the model-facing boundary (tool
  parameter schemas).
- Keep the loop a mechanism and put policy (permissions, persistence) in the app layer.
- No linter is configured yet; match the surrounding style.

## Releasing

py-agent isn't published to PyPI; install it from the repo (`uv tool install .`). It has no
non-PyPI dependencies — just `httpx`, `pydantic`, and `rich`.
