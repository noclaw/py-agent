# 4. Production seams

**Parts:** policy seams (5)

You now have a working, interactive agent. This tutorial is about everything that stands
between "works in a demo" and "survives a real session": observation, persistence, staying
under the context window, recovering from flaky networks, and delegation.

The throughline: **none of these live in the loop.** Each is a *seam* — a small, optional
hook the loop exposes — and the policy plugs in from the app layer. That's why `run_agent`
stays readable while the app gets to be opinionated. We'll take them in the order they bite
you.

## Hooks — observe and override, without forking the loop

Tutorial 2's permissions answer "may this run?" Hooks answer the broader "do something at
these moments." `agent/hooks.py` fires callbacks at three points, same shapes as Claude
Code:

- **`PreToolUse`** — before a tool runs; can `allow` (skip the permission check) or `deny`
  (block it). This runs *before* permissions in the gate.
- **`PostToolUse`** — after a tool runs; can attach `additional_context` that's appended to
  the result the model sees.
- **`UserPromptSubmit`** — when the user submits a prompt; can add context.

```python
from agent.hooks import Hooks, HookResult

hooks = Hooks()

@hooks.pre_tool_use(matcher="bash")
def block_force_push(event):
    if "push --force" in event.tool_input.get("command", ""):
        return HookResult(decision="deny", reason="no force pushes")

run_agent(model, tools, history, hooks=hooks, ...)
```

The loop calls hooks inside `_gate` (PreToolUse) and `_post_tool_use` (PostToolUse); the
REPL ships a default `UserPromptSubmit` hook that tags each prompt with the current git
branch. Hooks are how you add cross-cutting behavior — audit logs, guardrails, injected
context — without editing `run_agent`. See [hooks](../hooks.md).

## Sessions — the transcript is already the state

Because the loop mutates `history` in place (Tutorial 1), persistence is almost free: write
the message list to disk after each turn, read it back to resume. `agent/sessions.py`
stores one JSONL file per conversation under `~/.pya/sessions/`, tagged with the working
directory so `pya -c` resumes the right project's chat.

The serialization is the same `message_to_wire` / `message_from_wire` pair the model layer
uses (`agent/types.py`) — so a resumed assistant message is byte-for-byte what the provider
streamed, preserving thinking blocks and tool-call signatures that some providers require
for continuity. No separate "save format" to keep in sync. See [sessions](../sessions.md).

## Compaction — staying under the context window

Every turn resends the whole history (Tutorial 1), so a long session eventually approaches
the model's context limit. Compaction summarizes the oldest turns into one synthetic
message and keeps the recent tail.

This is the cleanest example of a seam. `run_agent` exposes one callback,
`transform_context`, run **before each turn's stream**, that may return a replacement
history:

```python
# in loop.py, before streaming each turn:
if transform_context is not None:
    transformed = await transform_context(history, emit_event)
    if transformed is not None:
        history[:] = transformed
```

The loop knows *nothing* about summarization — it just offers "you may rewrite the context
now." `agent/compaction.py`'s `Compactor` plugs into that seam: it estimates token
footprint from the last assistant message's `usage`, and once history exceeds
`threshold × context_window` it summarizes all but the most recent messages (nudging the
split so it never orphans a tool result from its call). It emits `CompactionStart` /
`CompactionEnd` so the renderer can show it. Wire it with
`transform_context=Compactor(model, CompactionConfig(max_tokens=200_000)).transform`
(`CompactionConfig` also has `threshold` and `keep_recent`). See
[the agent loop › compaction](../agent-loop.md#compaction).

## Auto-retry — surviving a flaky turn

A failed turn surfaces as a terminal `error` event (the final `AssistantMessage` has
`stopReason == "error"`). That makes retry a tidy wrapper around the per-turn stream: if a
turn ends in `error` (never a user `aborted`), wait a backed-off delay and stream the same
turn again, up to `max_retries`. It lives in `_stream_turn` and emits `AgentRetry` events;
the policy is a plain dataclass:

```python
from agent.retry import RetryPolicy
run_agent(model, tools, history, retry=RetryPolicy(max_retries=2), ...)
```

Note the layering: retry wraps a *single turn's stream*, inside the loop's turn iteration —
so a retried turn is invisible to the history and to tool execution. See
[the agent loop › auto-retry](../agent-loop.md#auto-retry).

## Sub-agents — delegation as a tool

Sometimes a turn needs a self-contained chunk of work ("explore the codebase and report
the auth flow") that would flood the main conversation with intermediate tool calls. The
`task` tool (`agent/tools/task.py`) solves this elegantly: it's a tool whose `execute` runs
a **nested `run_agent`** with its own toolset and turn budget, and returns only the child's
final report. The parent's history stays clean.

It's the same loop calling itself — the clearest sign the loop is the right abstraction.
The child never gets a `task` tool of its own (no unbounded recursion) and runs sequentially
so its stream doesn't overlap the parent's. Add it by wrapping your toolset with
`with_task_tool(tools, ...)`; it's on by default in the CLI (disable with `--no-subagent`).
See [tools › sub-agents](../tools.md#sub-agents-the-task-tool).

## The pattern

Look at what every section had in common: the loop offers a **named moment** (before a tool,
after a tool, before a turn, when a turn fails, as a tool), and the app supplies behavior.
Permissions, hooks, retry, compaction, sub-agents — all the same move. When you need new
behavior, the question is "which seam?" not "how do I change the loop?". If none fits, that's
the signal to add a seam, deliberately — not to thread a special case through `run_agent`.

## Try this

1. Add a `PostToolUse` hook on `read` that appends the file's line count as
   `additional_context`, and watch the model use it.
2. Run a long conversation with a small `--context-window` and watch the
   `⊟ compacting context…` line fire, then confirm the chat still makes sense.
3. Read `agent/tools/task.py` and trace the nested `run_agent` call — note where the child's
   tools and `max_turns` come from.

## Anatomy recap

You learned the fifth part in depth: **policy seams**. The loop stays mechanism; hooks,
sessions, compaction, retry, and sub-agents are all policy hung on well-named moments around
it. That's the design that lets one ~360-line loop be both a demo and a real tool. Last
step: point all of this at a different problem.

**Next:** [Make it your own →](05-make-it-your-own.md)
Reference: [hooks](../hooks.md) · [sessions](../sessions.md) · [agent loop](../agent-loop.md) · `agent/compaction.py`, `agent/retry.py`, `agent/tools/task.py`
