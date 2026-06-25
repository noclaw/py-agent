# The agent loop

A guided read of `src/agent/loop.py` — the heart of the agent. If you read one file to
understand py-agent, read that one; this is the map.

## Public shape

```python
async def run_agent(
    model, tools, history, *,
    system_prompt=None, hooks=None, permissions=None, approver=None, max_turns=50,
    retry=None, transform_context=None,
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
`AgentEnd(reason)` where reason is `"completed"`, `"error"`, or `"aborted"`. Two optional
features add their own events: `AgentRetry` ([auto-retry](#auto-retry)) and
`CompactionStart`/`CompactionEnd` ([compaction](#compaction)).

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
  if transform_context: history = transform_context(history, emit) or history   # e.g. compaction
  emit TurnStart
  assistant = _stream_turn(...)       # stream the assistant, retrying transient errors
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

### Auto-retry

`_stream_turn` streams one assistant turn and, if it ends in a transient model error
(pi-ai's terminal `error` event), re-streams it per the `retry` policy
([`RetryPolicy`](../src/agent/retry.py): exponential backoff, capped). A user `aborted` is
never retried. Each retry emits an `AgentRetry(attempt, max_retries, delay, error)` event,
then the loop sleeps the backoff and tries again; once retries are exhausted the error
message is returned and the run ends `"error"`. With `retry=None` (the default for
`run_agent`) a turn is streamed exactly once. The CLI sets it via `--max-retries` (default 2).

### Compaction

`transform_context(history, emit)` runs once per turn **before** streaming and may return a
replacement history — the seam [compaction](../PLAN.md) plugs into. `agent.compaction.Compactor`
estimates the token footprint (from the last assistant message's reported `usage`, with a
char-count fallback) and, once it exceeds `threshold × context_window`, summarizes all but
the most recent K messages into a single synthetic user message — emitting
`CompactionStart`/`CompactionEnd`. The split point is nudged back so it never orphans a
tool-result from its tool call. The CLI enables it by default (`--no-compact`,
`--context-window`).

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
`permissions`, `approver`, `retry` policy, and `transform_context`. The last is the general
context-rewrite seam — [compaction](#compaction) is its canonical use, but anything that
rewrites history before a turn (redaction, pruning, re-ranking retrieved context) fits there.
