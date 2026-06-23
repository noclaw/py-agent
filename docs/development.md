# Development

## Layout

```
src/agent/        the package (see architecture.md for the module map)
tests/            pytest; unit tests need no Node (a scripted fake model stands in)
docs/             these docs
PLAN.md           status + remaining optional phases
```

## Setup

```bash
uv sync --extra dev
```

This pulls `pi-py-sdk` from PyPI, so the repo is self-contained. To develop against a
local `pi-py` checkout (e.g. to change the model shim), add to `pyproject.toml`:

```toml
[tool.uv.sources]
pi-py-sdk = { path = "../pi-py", editable = true }
```

then `uv sync` again. (Reminder: virtualenvs aren't relocatable — if you move/rename the
repo directory, `rm -rf .venv && uv sync` to rebuild it.)

## Tests

```bash
uv run pytest                         # unit tests (no Node, no network)
uv run pytest -m integration          # live tests (need Node + pi-ai)
PI_LIVE_LLM=1 uv run pytest -m integration   # also the tests that call a model
```

Integration tests are skipped unless `pi`/`node` are present, and the ones that call a
model additionally require `PI_LIVE_LLM=1` (so the default `uv run pytest` never hits the
network). They default to a cheap model; override with `PI_LIVE_MODEL` / `PI_LIVE_PROVIDER`.

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

py-agent isn't published to PyPI. The model SDK it depends on, `pi-py-sdk`, is — see that
repo for its release flow (a GitHub Release triggers a Trusted-Publishing workflow).
