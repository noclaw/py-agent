# CLAUDE.md

Guidance for working in this repository.

## What this is

`py-agent` is a readable, standalone Python coding agent. **The whole thing is Python**
— the agent loop, the tools, and the model layer, which talks directly to provider HTTP
APIs over `httpx`. No Node, no shim. It is
an *example implementation* — optimized for being read and modified (learning Python; a base
for assistant / second-brain agents), not for maximal features.

**Core principle:** keep everything readable Python, in-process. The model layer lives in
`agent/providers/` (`openai-completions` and `anthropic-messages` backends); add a provider
by implementing the small `Provider` protocol. We deliberately support a limited set of
providers — exotic transports (Bedrock/Vertex/Azure) are a user's custom code, not ours.

## Layout

```
src/agent/
  cli.py            # `pya` entry point
  app.py            # REPL + one-shot runner; policy wiring (perms/hooks/retry/compaction)
  loop.py           # the agent loop
  types.py          # AgentMessage, events, Tool protocol
  model.py          # Model adapter: routes a turn to a native provider by API flavor
  wire.py           # native StreamEvent / AssistantMessage / ToolCall (the model contract)
  providers/        # native httpx model layer: openai_compat, anthropic, catalog, auth, oauth
  models_registry.py# custom/local models from .pya/models.json
  settings.py       # ~/.pya/settings.toml: provider keys, allowlist, default
  picker.py         # fuzzy model picker for /model
  system_prompt.py  # build_system_prompt
  config.py         # settings + defaults
  render.py         # event -> terminal rendering
  permissions.py    # tool gating: modes + allow/deny rules + approval (per-tool policy)
  hooks.py          # PreToolUse / PostToolUse / UserPromptSubmit callbacks
  commands.py       # slash commands + custom markdown commands
  sessions.py       # JSONL save/resume
  skills.py         # progressive-disclosure SKILL.md discovery + prompt block
  compaction.py     # context compaction (transform_context seam)
  retry.py          # RetryPolicy for transient model errors
  checkpoints.py    # file-edit snapshots for /checkpoints and /rewind
  tools/            # read/write/edit/bash/grep/find/ls + web + memory + todo + task (sub-agent);
                    #   one BUILTIN_TOOL_CLASSES registry, each tool owns its gating policy
tests/              # pytest; unit tests use a fake model (no network)
docs/               # design + usage guides (start at docs/README.md)
PLAN.md             # status + Potential Features roadmap
```

## The model layer (`agent/providers/`)

Native Python over `httpx` — no subprocess. The pieces:

- `wire.py` — `StreamEvent` / `AssistantMessage` / `ToolCall`: the contract the loop,
  renderer, and sessions speak. A provider's job is to turn its HTTP stream into these.
- `providers/base.py` — the `Provider` protocol: `stream(...)` + `list_models()`.
- `providers/openai_compat.py` — OpenAI Chat Completions (OpenAI + local/OpenAI-compatible).
- `providers/anthropic.py` — Anthropic Messages (streaming, thinking + signature, tool use).
- `providers/auth.py` — credential resolution (spec key → env var → `pya auth` → settings).
- `providers/oauth.py` — generic OAuth toolkit (provider-neutral; not wired to a provider today).
- `providers/catalog.py` — static routing (provider → api/baseUrl/env) + a curated model list.
- `providers/http.py` — shared httpx SSE iteration; `providers/errors.py` — `ProviderError`.

`model.py` selects a provider by the model's `api` (`openai-completions` / `anthropic-messages`),
resolved from the catalog (built-ins) or a `.pya/models.json` spec (custom/local). To stream
a transport we don't ship, implement `Provider` and register the model under a custom `api`.

## Conventions

4-space indent, type hints, `from __future__ import annotations`,
Google-ish docstrings. No linter configured yet. Async-first; provide sync where it helps
the CLI.

## Testing approach

The key fixture is a **fake model** (scripted `StreamEvent` sequences) so the loop and
tools are tested without the network. Providers are tested with `httpx.MockTransport` fed
canned SSE — also no network. Live model calls go behind the `integration` marker and are
skipped unless `PYA_LIVE_LLM=1` (and `ANTHROPIC_API_KEY` is set).

## Status

All seven core phases, the Claude-Code-shaped extras (permissions, hooks, commands,
sessions, skills, compaction, auto-retry, sub-agents), the model registry + `/model` picker,
the settings/credential layer (`settings.toml`, `pya auth`/`pya config`), web tools, edit
checkpoints, and the **native provider layer** are built — see `PLAN.md` for the full status
and the **Potential Features** list (memory tools, images, todo/planning, token-cost budget,
MCP, …) for anything new. Keep changes scoped and the loop/tools readable; put policy in the
app layer, not the loop.

## Git

Work on a feature branch and fast-forward into `main`. End commit messages with the
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer.
