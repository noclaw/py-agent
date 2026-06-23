# The agent loop

A guided read of `src/agent/loop.py` — the heart of the agent. If you read one file to
understand py-agent, read that one; this is the map.

## Public shape

```python
async def run_agent(
    model, tools, history, *,
    system_prompt=None, hooks=None, permissions=None, approver=None, max_turns=50,
) -> AsyncIterator[AgentEvent]: ...
```

It's an **async generator of events**. You drive it and render the events:

```python
history = [user_message("...")]
async for event in run_agent(model, tools, history, system_prompt=sp):
    render(event)         # history is mutated in place as the run progresses
```

The events (`agent.types`): `AgentStart`, `TurnStart`, `AssistantDelta` (wraps a raw
`StreamEvent`), `AssistantDone`, `ToolStart`, `ToolOutput`, `ToolEnd`, `TurnEnd`,
`AgentEnd(reason)` where reason is `"completed"`, `"error"`, or `"aborted"`.

## Why a queue

A turn is sequential, but tools can run **concurrently** and **stream** output — and a
concurrent task can't `yield` from the generator's frame. So `run_agent` runs the real
work in a `producer` task that pushes events onto an `asyncio.Queue`, and the generator
just drains the queue. That keeps the public API a simple `async for` while supporting
parallel, streaming tools. On consumer cancellation the producer is cancelled too (which
propagates into running tools — e.g. `bash` kills its process group).

## `_drive` — one turn at a time

```
emit AgentStart
loop:
  turn += 1; if turn > max_turns: emit AgentEnd("error"); stop
  emit TurnStart
  # stream the assistant
  for event in model.stream(system_prompt, to_llm_messages(history), tools):
      emit AssistantDelta(event)
      if event.is_terminal: assistant = event.final_message
  append assistant to history; emit AssistantDone
  if assistant.stopReason in ("error","aborted"): emit AgentEnd(...); stop
  calls = tool calls in the assistant message
  if no calls: emit AgentEnd("completed"); stop
  results = execute(calls)            # see below
  history.extend(results); emit TurnEnd
```

History is converted to wire messages each turn via `to_llm_messages` (the `convertToLlm`
seam). The terminal `done`/`error` event carries the final assistant message, so there's
no delta accumulation to do.

## `_execute_tool_calls` — gate then run

```
sequential = any called tool has execution_mode == "sequential"
gate_lock = asyncio.Lock()      # serializes approval prompts only
for each call (parallel by default):
    emit ToolStart
    async with gate_lock: blocked = _gate(call)      # hooks → permissions → approver
    result = blocked or await tool.execute(args, on_update=...)
    result = _post_tool_use(result)                  # PostToolUse hooks
    emit ToolEnd
    return a toolResult message
```

- **Gating** (`_gate`): [PreToolUse hooks](hooks.md) can `allow`/`deny`; otherwise the
  [permission policy](permissions.md) returns allow/deny/ask, and "ask" calls the approver.
  A blocked call becomes an error `ToolResult` instead of running.
- **Validation**: raw arguments are validated against the tool's Pydantic `parameters`; a
  `ValidationError` becomes an error result.
- **Isolation**: a tool that raises is caught and reported to the model as an error — one
  bad tool won't kill the run.
- **Ordering**: results are returned in call order (providers expect a `toolResult` per
  `toolCall`), even when execution is parallel.

## Extending the loop

Everything is injected, so you rarely edit `loop.py`: pass your own `tools`, `hooks`,
`permissions`, and `approver`. The one seam not yet wired is `transform_context` (for
[compaction](../PLAN.md)); that's the natural place to add it.
