"""The agent loop — the heart of the agent.

Port target: ``packages/agent/src/agent-loop.ts``.

``run_agent`` is an async generator of :mod:`~agent.types` events. Each turn it
streams one assistant response, executes any tool calls the model made, feeds the results
back into the conversation, and repeats until the model stops calling tools (or an error /
turn cap / cancellation ends the run). It mutates ``history`` in place so the caller keeps
the full transcript.

Why a queue: a turn is sequential, but tool execution can run several tools concurrently
and stream their output. Concurrent tasks can't ``yield`` from this generator's frame, so
they push events onto an :class:`asyncio.Queue` that the generator drains. This keeps the
public API a simple ``async for`` while supporting parallel, streaming tools.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator

from pydantic import ValidationError

from .model import ModelLike
from .types import (
    AgentEnd,
    AgentEvent,
    AgentMessage,
    AgentStart,
    AssistantDelta,
    AssistantDone,
    Tool,
    ToolEnd,
    ToolOutput,
    ToolResult,
    ToolResultMessage,
    ToolStart,
    TurnEnd,
    TurnStart,
    to_llm_messages,
    tool_result_message,
    tools_to_wire,
)

#: Safety cap so a misbehaving model can't loop forever.
DEFAULT_MAX_TURNS = 50


@dataclass
class _ToolCallRef:
    """A normalized view of a tool-call content block (dict or model)."""

    id: str
    name: str
    arguments: dict[str, Any]


def _extract_tool_calls(message: Any) -> list[_ToolCallRef]:
    calls: list[_ToolCallRef] = []
    for block in getattr(message, "content", None) or []:
        is_dict = isinstance(block, dict)
        btype = block.get("type") if is_dict else getattr(block, "type", None)
        if btype != "toolCall":
            continue
        if is_dict:
            calls.append(_ToolCallRef(block.get("id", ""), block.get("name", ""), block.get("arguments") or {}))
        else:
            calls.append(
                _ToolCallRef(
                    getattr(block, "id", ""),
                    getattr(block, "name", ""),
                    getattr(block, "arguments", None) or {},
                )
            )
    return calls


async def run_agent(
    model: ModelLike,
    tools: list[Tool],
    history: list[AgentMessage],
    *,
    system_prompt: str | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> AsyncIterator[AgentEvent]:
    """Run the agent to completion, yielding events. ``history`` is appended to in place.

    Drive it with::

        history = [user_message("...")]
        async for event in run_agent(model, tools, history, system_prompt=sp):
            render(event)
    """
    queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
    done = object()

    async def producer() -> None:
        try:
            await _drive(model, tools, history, system_prompt, max_turns, queue)
        finally:
            queue.put_nowait(done)  # type: ignore[arg-type]

    task = asyncio.create_task(producer())
    try:
        while True:
            event = await queue.get()
            if event is done:
                break
            yield event
        await task  # surface any exception raised inside the producer
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def _drive(
    model: ModelLike,
    tools: list[Tool],
    history: list[AgentMessage],
    system_prompt: str | None,
    max_turns: int,
    queue: asyncio.Queue[AgentEvent],
) -> None:
    tools_by_name = {tool.name: tool for tool in tools}
    wire_tools = tools_to_wire(tools) if tools else None

    queue.put_nowait(AgentStart())
    turn = 0
    while True:
        turn += 1
        if turn > max_turns:
            queue.put_nowait(AgentEnd("error"))
            return
        queue.put_nowait(TurnStart(turn))

        # 1. Stream the assistant response for this turn.
        assistant = None
        async for event in model.stream(
            system_prompt=system_prompt,
            messages=to_llm_messages(history),
            tools=wire_tools,
        ):
            queue.put_nowait(AssistantDelta(event))
            if event.is_terminal:
                assistant = event.final_message

        if assistant is None:
            queue.put_nowait(AgentEnd("error"))
            return

        history.append(assistant)
        queue.put_nowait(AssistantDone(assistant))

        stop = getattr(assistant, "stopReason", None)
        if stop in ("error", "aborted"):
            queue.put_nowait(TurnEnd(turn))
            queue.put_nowait(AgentEnd(stop))
            return

        # 2. Execute tool calls, if any.
        calls = _extract_tool_calls(assistant)
        if not calls:
            queue.put_nowait(TurnEnd(turn))
            queue.put_nowait(AgentEnd("completed"))
            return

        results = await _execute_tool_calls(calls, tools_by_name, queue)
        history.extend(results)
        queue.put_nowait(TurnEnd(turn))
        # 3. Loop: the model sees the tool results on the next turn.


async def _execute_tool_calls(
    calls: list[_ToolCallRef],
    tools_by_name: dict[str, Tool],
    queue: asyncio.Queue[AgentEvent],
) -> list[ToolResultMessage]:
    """Run a batch of tool calls and return their result messages (in call order).

    Runs in parallel by default; falls back to sequential if any called tool declares
    ``execution_mode == "sequential"``.
    """
    sequential = any(
        tools_by_name[c.name].execution_mode == "sequential"
        for c in calls
        if c.name in tools_by_name
    )

    async def run_one(call: _ToolCallRef) -> ToolResultMessage:
        queue.put_nowait(ToolStart(call.id, call.name, call.arguments))
        result = await _run_single_tool(call, tools_by_name, queue)
        queue.put_nowait(ToolEnd(call.id, call.name, result))
        return tool_result_message(call.id, call.name, result.content, is_error=result.is_error)

    if sequential:
        return [await run_one(call) for call in calls]
    return list(await asyncio.gather(*(run_one(call) for call in calls)))


async def _run_single_tool(
    call: _ToolCallRef,
    tools_by_name: dict[str, Tool],
    queue: asyncio.Queue[AgentEvent],
) -> ToolResult:
    tool = tools_by_name.get(call.name)
    if tool is None:
        return ToolResult(content=f"Unknown tool: {call.name}", is_error=True)

    try:
        args = tool.parameters.model_validate(call.arguments)
    except ValidationError as exc:
        return ToolResult(content=f"Invalid arguments for {call.name}: {exc}", is_error=True)

    def on_update(chunk: str) -> None:
        queue.put_nowait(ToolOutput(call.id, call.name, chunk))

    try:
        return await tool.execute(args, on_update=on_update)
    except asyncio.CancelledError:
        raise  # let cancellation propagate (the tool cleaned up in its own finally)
    except Exception as exc:  # noqa: BLE001 — a tool bug shouldn't kill the whole run
        return ToolResult(content=f"Tool {call.name} raised: {exc}", is_error=True)
