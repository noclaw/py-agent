# Architecture

py-agent splits cleanly along the same lines as [Pi](https://pi.dev), which ships as three
layered npm packages:

| Layer | Pi package | py-agent |
|---|---|---|
| Model / provider / streaming / auth | `@earendil-works/pi-ai` | **reused** as a black box |
| Generic agent loop + harness | `@earendil-works/pi-agent-core` | **ported to Python** |
| Coding product (tools, prompt, sessions, commands) | `@earendil-works/pi-coding-agent` | **ported to Python** |

The bet: the model layer (30+ providers, OAuth, transports, local models) is large,
well-tested, and not interesting to reimplement — so we keep it. The loop and tools are
the parts worth reading and customizing, so those are plain Python here.

## The Node shim

There is no Pi mode that streams *raw model output* without running the whole agent. So
the `pi-py` SDK gained a small Node script (`pi_py_sdk/_shim/stream.mjs`) that imports
`pi-ai` and exposes its `streamSimple` over JSONL on stdin/stdout. The Python side talks
to it through `pi_py_sdk.PiModelClient`.

```
┌─────────────────────────── Python (py-agent) ────────────────────────────┐
│  cli / app / render                                                       │
│  loop  ──>  tools (read/write/edit/bash/grep/find/ls)                     │
│    │        each tool call gated by:  hooks → permissions → approval      │
│    │ per turn: stream(context = system prompt + messages + tools)         │
│    ▼                                                                      │
│  pi_py_sdk.PiModelClient  ──JSONL over a subprocess──┐                    │
└───────────────────────────────────────────────────────┼──────────────────┘
                                                         ▼
              Node shim (stream.mjs)  ──imports──>  @earendil-works/pi-ai
              (providers, auth, transports, local models)
```

Only the LLM call crosses into Node. Everything else — turn structure, tool execution,
permissions, sessions, the prompt — is Python you can read in `src/agent/`.

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
  model.py          Model adapter over pi_py_sdk.PiModelClient; open_model()
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
