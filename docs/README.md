# py-agent docs

py-agent is a readable Python coding agent: the loop and tools are Python, the model
layer is delegated to Pi's `pi-ai` via the `pi-py` SDK. These docs explain the design and
the extension seams. The [top-level README](../README.md) is the quick tour; start there
to install and run.

## Understand it
- [Architecture](architecture.md) — the layering, the Node shim, and a turn's lifecycle.
- [The agent loop](agent-loop.md) — a guided read of `loop.py`.
- [Models & providers](models-and-providers.md) — how the model layer works, credentials,
  local models, switching models.

## Use it
- [Quickstart](../QUICKSTART.md) — zero to a first turn in a few minutes.
- [Getting started](getting-started.md) — install (incl. global `pya`), configure a
  provider, select a model, troubleshooting.
- [Configuration](configuration.md) — flags, env vars, and the `.pya/` directory layout.
- [Sessions](sessions.md) — save and resume conversations.

## Learn it
- [Tutorials](tutorials/README.md) — build up how an agent works, part by part, mapped to
  the code in this repo.

## Extend it (the seams)
- [Tools](tools.md) — write a custom tool.
- [Hooks](hooks.md) — run callbacks at PreToolUse / PostToolUse / UserPromptSubmit.
- [Permissions](permissions.md) — gate mutating tools (modes, rules, approval).
- [Commands](commands.md) — built-in slash commands and custom markdown commands.
- [Skills](skills.md) — teach the agent workflows with `SKILL.md`.
- [**Building your own agent**](building-your-own-agent.md) — drive the loop
  programmatically and swap the toolset (e.g. a second-brain assistant).

## Contribute
- [Development](development.md) — layout, tests, conventions.
