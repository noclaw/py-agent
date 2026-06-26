"""The agent loop — the heart of the agent.

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
import inspect
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Union

from pydantic import ValidationError

from .hooks import Hooks, PostToolUse, PreToolUse
from .model import ModelLike
from .permissions import Permissions
from .retry import RetryPolicy
from .types import (
    AgentEnd,
    AgentEvent,
    AgentMessage,
    AgentRetry,
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

#: An approver decides an "ask" permission interactively. Given (tool_name, args, reason),
#: it returns "once" (allow this call), "always" (allow + remember a rule), or "deny".
#: May be sync or async.
Approver = Callable[[str, dict[str, Any], Union[str, None]], Union[str, Awaitable[str]]]

#: Called before each turn's stream with the current history and an event-emit channel; may
#: return a replacement history (e.g. compacted) or ``None`` to leave it unchanged. This is
#: the seam :class:`agent.compaction.Compactor` plugs into.
ContextTransform = Callable[
    [list[AgentMessage], Callable[[AgentEvent], None]],
    Awaitable[Union[list[AgentMessage], None]],
]


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
    hooks: Hooks | None = None,
    permissions: Permissions | None = None,
    approver: Approver | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    retry: RetryPolicy | None = None,
    transform_context: ContextTransform | None = None,
) -> AsyncIterator[AgentEvent]:
    """Run the agent to completion, yielding events. ``history`` is appended to in place.

    Args:
        hooks: optional :class:`~agent.hooks.Hooks` (PreToolUse/PostToolUse callbacks).
        permissions: optional :class:`~agent.permissions.Permissions`; when ``None`` every
            tool call runs (the library default — the app layer sets policy).
        approver: called when permissions say "ask"; see :data:`Approver`.
        retry: optional :class:`~agent.retry.RetryPolicy`; re-streams a turn that ends in a
            transient model error (never a user ``aborted``).
        transform_context: optional :data:`ContextTransform` run before each turn — the seam
            compaction plugs into.

    Drive it with::

        history = [user_message("...")]
        async for event in run_agent(model, tools, history, system_prompt=sp):
            render(event)
    """
    queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
    done = object()

    async def producer() -> None:
        try:
            await _drive(
                model, tools, history, system_prompt, max_turns, queue,
                hooks, permissions, approver, retry, transform_context,
            )
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
    hooks: Hooks | None,
    permissions: Permissions | None,
    approver: Approver | None,
    retry: RetryPolicy | None,
    transform_context: ContextTransform | None,
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

        # 0. Optionally rewrite the context (e.g. compaction) before streaming.
        if transform_context is not None:
            transformed = await transform_context(history, queue.put_nowait)
            if transformed is not None:
                history[:] = transformed

        queue.put_nowait(TurnStart(turn))

        # 1. Stream the assistant response for this turn (retrying transient errors).
        assistant = await _stream_turn(
            model, system_prompt, history, wire_tools, queue, retry
        )

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

        results = await _execute_tool_calls(calls, tools_by_name, queue, hooks, permissions, approver)
        history.extend(results)
        queue.put_nowait(TurnEnd(turn))
        # 3. Loop: the model sees the tool results on the next turn.


async def _stream_turn(
    model: ModelLike,
    system_prompt: str | None,
    history: list[AgentMessage],
    wire_tools: list[dict[str, Any]] | None,
    queue: asyncio.Queue[AgentEvent],
    retry: RetryPolicy | None,
) -> Any | None:
    """Stream one assistant turn, retrying transient errors per ``retry``.

    Returns the final assistant message, or ``None`` if the stream produced no terminal
    event even after retries. A user ``aborted`` is returned as-is (never retried).
    """
    max_retries = retry.max_retries if retry is not None else 0
    attempt = 0
    while True:
        assistant = None
        async for event in model.stream(
            system_prompt=system_prompt,
            messages=to_llm_messages(history),
            tools=wire_tools,
        ):
            queue.put_nowait(AssistantDelta(event))
            if event.is_terminal:
                assistant = event.final_message

        stop = getattr(assistant, "stopReason", None) if assistant is not None else "error"
        if stop != "error" or attempt >= max_retries:
            return assistant

        attempt += 1
        delay = retry.delay_for(attempt)  # type: ignore[union-attr]  (retry set when max_retries>0)
        error_text = getattr(assistant, "errorMessage", None) if assistant is not None else None
        queue.put_nowait(AgentRetry(attempt, max_retries, delay, error_text))
        await asyncio.sleep(delay)


async def _execute_tool_calls(
    calls: list[_ToolCallRef],
    tools_by_name: dict[str, Tool],
    queue: asyncio.Queue[AgentEvent],
    hooks: Hooks | None,
    permissions: Permissions | None,
    approver: Approver | None,
) -> list[ToolResultMessage]:
    """Run a batch of tool calls and return their result messages (in call order).

    Runs in parallel by default; falls back to sequential if any called tool declares
    ``execution_mode == "sequential"``. Gating (hooks + permissions + approval) is
    serialized by a lock so interactive approval prompts never interleave, while the
    actual tool work still overlaps.
    """
    sequential = any(
        tools_by_name[c.name].execution_mode == "sequential"
        for c in calls
        if c.name in tools_by_name
    )
    gate_lock = asyncio.Lock()

    async def run_one(call: _ToolCallRef) -> ToolResultMessage:
        queue.put_nowait(ToolStart(call.id, call.name, call.arguments))
        async with gate_lock:
            blocked = await _gate(call, hooks, permissions, approver)
        result = blocked if blocked is not None else await _run_single_tool(call, tools_by_name, queue)
        result = await _post_tool_use(call, result, hooks)
        queue.put_nowait(ToolEnd(call.id, call.name, result))
        return tool_result_message(call.id, call.name, result.content, is_error=result.is_error)

    if sequential:
        return [await run_one(call) for call in calls]
    return list(await asyncio.gather(*(run_one(call) for call in calls)))


async def _gate(
    call: _ToolCallRef,
    hooks: Hooks | None,
    permissions: Permissions | None,
    approver: Approver | None,
) -> ToolResult | None:
    """Decide whether ``call`` may run. Returns a blocking :class:`ToolResult`, or ``None``
    to allow. Order mirrors Claude Code: PreToolUse hooks, then the permission policy."""
    if hooks is not None:
        for result in await hooks.run(PreToolUse(call.name, call.arguments, call.id)):
            if result.decision == "deny":
                return ToolResult(content=f"Blocked by hook: {result.reason or 'denied'}", is_error=True)
            if result.decision == "allow":
                return None  # hook explicitly allowed → skip the permission check

    if permissions is None:
        return None

    decision = permissions.decide(call.name, call.arguments)
    if decision == "deny":
        return ToolResult(content=f"Permission denied for {call.name}.", is_error=True)
    if decision == "ask":
        if approver is None:
            return ToolResult(
                content=f"{call.name} requires approval, but no approver is configured.",
                is_error=True,
            )
        choice = approver(call.name, call.arguments, None)
        if inspect.isawaitable(choice):
            choice = await choice
        if choice == "always":
            permissions.allow_always(call.name, call.arguments)
        elif choice != "once":
            return ToolResult(content=f"Denied by user: {call.name}.", is_error=True)
    return None


async def _post_tool_use(call: _ToolCallRef, result: ToolResult, hooks: Hooks | None) -> ToolResult:
    """Run PostToolUse hooks; fold any additional context into the result."""
    if hooks is None:
        return result
    for hook_result in await hooks.run(PostToolUse(call.name, call.arguments, call.id, result)):
        if hook_result.additional_context:
            result = ToolResult(
                content=result.content + "\n\n" + hook_result.additional_context,
                details=result.details,
                is_error=result.is_error,
            )
    return result


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
