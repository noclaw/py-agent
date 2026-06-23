# CLAUDE.md

Guidance for working in this repository.

## What this is

`py-agent` is a Python port of the Pi coding agent. **The agent loop and tools are
written in Python here**; the **model layer** is delegated to Pi's `pi-ai` via the
`pi-py` SDK (`PiModelClient`). It is an *example implementation* — optimized for being
read and modified (learning Python; a base for assistant / second-brain agents), not for
maximal features.

**Core principle:** keep the loop and tools readable Python. Only the raw LLM call goes
out of process (to `pi-ai`, through `pi-py`). Do not reimplement providers/auth/transports
in Python — that's `pi-ai`'s job. Do not hide agent logic behind the Node runtime — that's
the whole point of writing it here.

## Layout

```
src/coding_agent/
  cli.py            # `pycoda` entry point                 (← coding-agent/src/cli)
  app.py            # REPL + one-shot runner
  loop.py           # the agent loop                       (← agent/src/agent-loop.ts)
  types.py          # AgentMessage, events, Tool protocol  (← agent/src/types.ts)
  model.py          # adapter over pi_py_sdk.PiModelClient + model registry
  system_prompt.py  # build_system_prompt                  (← coding-agent/.../system-prompt.ts)
  config.py         # settings + defaults                  (← coding-agent/src/config.ts)
  render.py         # event -> terminal rendering
  tools/            # read/write/edit/bash/grep/find/ls    (← coding-agent/.../tools/)
tests/              # pytest; unit tests need no Node (fake model)
PLAN.md             # phased roadmap + Pi module map
```

## Dependency on pi-py

`pi-py-sdk` (the `../pi-py` checkout) is the model bridge. The relevant entry point is
`PiModelClient`:

```python
async with PiModelClient() as client:
    async for ev in client.stream(provider=..., model=..., messages=..., tools=...):
        ...  # text_delta / thinking_delta / toolcall_end / terminal done|error
```

It's wired as an editable path dependency, so edits in `../pi-py` are picked up without
reinstalling. If you change the streaming protocol, change it there.

## Conventions

Match pi-py's style: 4-space indent, type hints, `from __future__ import annotations`,
Google-ish docstrings. No linter configured yet. Async-first; provide sync where it helps
the CLI.

## Testing approach

The key fixture is a **fake model** (scripted `StreamEvent` sequences) so the loop and
tools are tested without the network. Live model calls go behind the `integration` marker
and are skipped unless `PI_LIVE_LLM=1`.

## Phasing

Work proceeds in the phases in `PLAN.md` (currently: Phase 1 scaffold done; next is types
-> tools + loop -> prompt -> CLI/REPL). Keep changes scoped to the active phase.

## Git

Work on a feature branch and fast-forward into `main`. End commit messages with the
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer.
