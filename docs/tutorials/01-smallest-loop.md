# 1. The smallest agent loop

**Parts:** model adapter (1) · the loop (2) · context/history (4)

An "agent" sounds elaborate, but the core is a loop you could sketch on a napkin:

```
send the conversation to the model
while the model asked to call tools:
    run the tools
    append their results to the conversation
    send it back to the model
stop when the model replies with no tool calls
```

That's it. Everything else in this repo is features bolted around that loop. This tutorial
builds the loop from scratch so you can see there's no magic, then connects each piece to
the real code.

## What a "conversation" is

The model is stateless: every turn you send it the *whole* conversation so far. In
py-agent the conversation is a Python list of message objects — the **history** (part 4):

- a `UserMessage` (what the human typed),
- an `AssistantMessage` (what the model streamed back — kept verbatim, including any
  tool-call blocks),
- a `ToolResultMessage` (the output of a tool the model asked for).

The model doesn't speak Python objects, so just before each call we convert the list to the
provider's wire format with `to_llm_messages()`. That function is the `convertToLlm` seam —
the one place in-memory messages become the dicts the model sees. See `agent/types.py`.

## The model adapter

The only thing that leaves your process is the model call. `open_model()` hands you a
`Model` whose `.stream(...)` yields events as the response arrives:

```python
from agent.model import open_model

async with open_model(provider="anthropic", model="claude-sonnet-4-6") as model:
    async for event in model.stream(system_prompt=sp, messages=wire_messages, tools=wire_tools):
        # event.type is "text_delta", "thinking_delta", "toolcall_end", "done", "error", …
        ...
```

The stream **terminates** with a `done` or `error` event whose `.final_message` is the
complete `AssistantMessage` for the turn. The loop's job is to notice that final message,
check whether it contains tool calls, and decide whether to go around again. See
`agent/model.py` and [models & providers](../models-and-providers.md).

## The loop, by hand

Here's a complete agent in one function — no permissions, no rendering, one tool. Read it
top to bottom; it's the same shape as `run_agent`, minus the features.

```python
import asyncio
from agent.model import open_model
from agent.types import (
    user_message, to_llm_messages, tool_result_message, tools_to_wire,
)
from agent.tools.read import ReadTool

async def tiny_agent(prompt: str, cwd: str = "."):
    tools = [ReadTool(cwd)]
    tools_by_name = {t.name: t for t in tools}
    wire_tools = tools_to_wire(tools)
    history = [user_message(prompt)]               # (4) context

    async with open_model(provider="anthropic", model="claude-sonnet-4-6") as model:
        while True:
            # 1. stream one assistant turn (1)
            assistant = None
            async for event in model.stream(messages=to_llm_messages(history), tools=wire_tools):
                if event.is_terminal:
                    assistant = event.final_message
            history.append(assistant)

            # 2. find tool calls in what the model returned
            calls = [b for b in (assistant.content or []) if getattr(b, "type", None) == "toolCall"]
            if not calls:
                return assistant                    # no tools → the model is done

            # 3. run each tool, append its result, then loop (2)
            for call in calls:
                tool = tools_by_name[call.name]
                args = tool.parameters.model_validate(call.arguments)
                result = await tool.execute(args)
                history.append(tool_result_message(call.id, call.name, result.content,
                                                    is_error=result.is_error))

asyncio.run(tiny_agent("Read README.md and tell me the project's one-line description."))
```

Run it and the model will emit a `read` tool call, your loop executes it, the file contents
go back as a `ToolResultMessage`, and on the next turn the model answers from them — then
returns with no tool calls, ending the loop.

## What the real loop adds (and why)

`agent/loop.py`'s `run_agent` is this same skeleton with production concerns layered in.
None of them change the core; they wrap it:

- **It's an async generator of events**, not a function that returns at the end. The caller
  `async for`s over `AgentStart`, `TurnStart`, `AssistantDelta`, `ToolStart`, `ToolEnd`,
  `AgentEnd`, … so a UI can render *as it happens*. (Our toy only sees the final message.)
- **Tools run concurrently** when a turn calls several at once (via an `asyncio.Queue` so
  concurrent tasks can still emit events) — falling back to sequential when a tool asks for
  it. Tutorial 3 explains the queue.
- **A turn cap** (`max_turns`, default 50) so a misbehaving model can't loop forever.
- **Gates** between "the model asked" and "the tool runs" — permissions and hooks. That's
  Tutorial 2.
- **Stop reasons**: it distinguishes `completed` / `error` / `aborted` and surfaces them as
  `AgentEnd(reason=...)`.

Crucially, `run_agent` mutates `history` in place, exactly like our toy — so the caller
always holds the full transcript (that's what sessions persist, and what compaction
rewrites).

## Try this

1. Add a second tool to the toy (e.g. `from agent.tools.ls import LsTool`) and watch the
   model choose between them.
2. Print `event.delta` for `text_delta` events instead of only keeping the final message —
   you've just invented streaming output (Tutorial 3 makes it pretty).
3. Ask something that needs two tool calls in sequence and watch the `while` loop iterate.

## Anatomy recap

You touched three of the five parts: the **model adapter** (one streamed call out of
process), the **loop** (stream → run tools → feed back → repeat), and **context/history**
(the message list + `to_llm_messages`). Tools were along for the ride — next we build one
properly and learn how to keep it from doing something you didn't want.

**Next:** [Adding tools you can trust →](02-tools.md)
Reference: [the agent loop](../agent-loop.md) · `agent/loop.py`, `agent/types.py`, `agent/model.py`
