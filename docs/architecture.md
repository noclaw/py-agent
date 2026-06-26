# Architecture

py-agent is a standalone Python coding agent — every layer is plain Python:

| Layer | py-agent |
|---|---|
| Model / provider / streaming / auth | **native Python** (`agent/providers/`, httpx) |
| Generic agent loop + harness | **plain Python** (`loop.py`, `types.py`) |
| Coding product (tools, prompt, sessions, commands) | **plain Python** (`tools/`, `system_prompt.py`, `sessions.py`, `commands.py`) |

The native model layer is small and focused: we ship OpenAI-compatible + Anthropic; exotic
transports are user custom code (implement the `Provider` protocol). The tradeoff buys no
extra runtime, no out-of-process bridge, and full control of local models.

## The model layer

`model.py` routes a turn to a native provider by the model's API flavor; each provider
turns its HTTP/SSE stream into the `StreamEvent`s the loop consumes (`wire.py`).

```
┌─────────────────────────── Python (py-agent) ────────────────────────────┐
│  cli / app / render                                                       │
│  loop  ──>  tools (read/write/edit/bash/grep/find/ls)                     │
│    │        each tool call gated by:  hooks → permissions → approval      │
│    │ per turn: stream(context = system prompt + messages + tools)         │
│    ▼                                                                      │
│  model.py ──by api──> providers/ ──┐                                      │
│     openai_compat  ·  anthropic    │                                      │
└──────────────────────────────────────┼───────────────────────────────────┘
                                        ▼  httpx (SSE)
                          provider HTTP APIs (OpenAI-compatible / Anthropic)
```

Everything is in-process Python; only the HTTPS call leaves. To stream a transport we don't
ship, implement the `Provider` protocol (`providers/base.py`).

## A turn's lifecycle

`run_agent` (in `loop.py`) is an async generator of events. Each turn:

1. **Stream the assistant response.** Convert the in-memory history to wire messages
   (`to_llm_messages`), call `model.stream(system_prompt, messages, tools)`, and forward
   each `StreamEvent` as an `AssistantDelta`. The stream ends with a terminal `done`/`error`
   event carrying the final assistant message.
2. **Stop or continue.** If the assistant made no tool calls, emit `AgentEnd("completed")`.
   Otherwise:
3. **Gate each tool call** — PreToolUse hooks → permissions → (if "ask") the approver.
   A blocked call becomes an error result instead of running.
4. **Execute** the allowed calls (parallel by default; sequential if a tool requires it),
   streaming output via `ToolOutput`, then PostToolUse hooks.
5. **Feed results back** — append `toolResult` messages to history and loop. The model
   sees them on the next turn.

The loop mutates `history` in place, so the caller always holds the full transcript (for
rendering and for [session persistence](sessions.md)).

## Module map

```
src/agent/
  cli.py            argument parsing → app.run
  app.py            REPL + one-shot; builds Permissions, approver, registry, sessions
  loop.py           run_agent — the heart (turns, gating, tool execution, events)
  model.py          Model adapter: routes a turn to a native provider; open_model()
  wire.py           StreamEvent / AssistantMessage / ToolCall (the model-layer contract)
  providers/        native httpx model layer (openai_compat, anthropic, oauth, catalog)
  types.py          messages, the agent event taxonomy, the Tool protocol, converters
  system_prompt.py  build_system_prompt (tools + guidelines + skills + project context)
  render.py         event stream → terminal (rich)
  permissions.py    modes + allow/deny rules + decide()
  hooks.py          PreToolUse / PostToolUse / UserPromptSubmit
  commands.py       slash + markdown command registry
  skills.py         SKILL.md discovery + the <available_skills> prompt block
  sessions.py       JSONL save/resume
  tools/            read/write/edit/bash/grep/find/ls + base + registry
```

See [the agent loop](agent-loop.md) for a closer read of `loop.py`.
