# 3. Making it interactive

**Parts:** the loop (2) · policy seams (5)

Tutorials 1–2 produced a function you call once. A *usable* agent is a conversation: it
streams as it thinks, shows you each tool call, asks before doing something dangerous, and
takes another message when it's done. That's the **app layer** — `agent/app.py`,
`agent/render.py`, `agent/commands.py` — and it's where the loop becomes a REPL.

The app layer adds no agent intelligence. It does three jobs: **render** the event stream,
**run the loop** per user message, and **intercept** input that isn't a prompt (slash
commands). Keeping these out of `run_agent` is what lets the same loop power a one-shot
CLI, a REPL, or your own UI.

## Why the loop emits events

Recall from Tutorial 1 that `run_agent` is an *async generator of events*, not a function
that returns at the end. That's the whole basis of interactivity: the UI consumes events
the instant they happen.

```python
async for event in run_agent(model, tools, history, system_prompt=sp,
                             permissions=perms, approver=approver):
    renderer.handle(event)
```

The events form a predictable lifecycle (`agent/types.py`):

```
AgentStart
  TurnStart(1)
    AssistantDelta · AssistantDelta · …      # streamed text / thinking / tool-call deltas
    AssistantDone(message)                    # the turn's full assistant message
    ToolStart · ToolOutput* · ToolEnd         # one trio per tool call (may interleave)
  TurnEnd(1)
  TurnStart(2) … TurnEnd(2)                    # more turns if tools were called
AgentEnd(reason)                               # completed | error | aborted
```

## The renderer is just a switch on event type

`agent/render.py`'s `Renderer.handle(event)` is a readable `isinstance` ladder. The
essence:

- `AssistantDelta` → write `event.event.delta` as it streams (thinking shown dimmed);
- `ToolStart` → print `› toolname {args}`;
- `ToolEnd` → print `✓` or `✗` with the first line of the result;
- `AgentRetry` / `CompactionStart` / `CompactionEnd` → status lines (Tutorial 4);
- `AgentEnd` → a `— done (N tokens)` summary.

That's the entire UI. Because it only reads events, you can swap it for a GUI, a web
socket, or a test that asserts on the sequence — without touching the loop. The token count
in the summary comes from accumulating `message.usage` on each `AssistantDone`.

## Concurrency, briefly

When a turn calls several tools at once, they run concurrently — but a Python generator
can't `yield` from inside a spawned task. So `run_agent` has the tasks push events onto an
`asyncio.Queue` that the generator drains. That's why `ToolOutput` from two tools can
interleave while your `async for` stays a simple loop. You don't have to think about it to
use the loop; it's just why the public API can be this simple. See the "Why a queue" note
at the top of `agent/loop.py`.

## Slash commands: intercept before the loop

Not every line the user types should become a model turn. In the REPL, input starting with
`/` is a **command**, handled before the agent ever runs (`agent/commands.py`):

```python
user_input = read_line()
if user_input.startswith("/"):
    handled = commands.dispatch(user_input)   # /help, /model, /tools, /clear, /resume, …
    if handled:
        continue                              # never reaches the loop
history.append(user_message(user_input))      # otherwise it's a prompt
async for event in run_agent(...):
    renderer.handle(event)
```

Built-ins manage the *session*, not the conversation: `/model` switches the model mid-chat
(it just changes which id the next `stream` targets — see `Model.set_model`), `/clear`
starts fresh, `/tools` lists tools, `/resume` reloads a saved session. Custom commands are
markdown files under `.pya/commands/` whose body is a prompt template — those *do* become a
turn, after `$ARGUMENTS` expansion. See [commands](../commands.md).

## What `app.py` wires together

Putting it in order, the REPL is:

1. build tools (`coding_tools(cwd)`), the system prompt (`build_system_prompt`), the model
   (`open_model`), a `Renderer`, and a `Permissions` policy + `approver`;
2. loop on input → dispatch slash commands, else append a `user_message`;
3. `async for event in run_agent(...): renderer.handle(event)`;
4. on Ctrl-C, cancel the turn (the loop turns cancellation into `aborted`); on Ctrl-D, quit;
5. after each turn, save the session (Tutorial 4).

The **one-shot** path (`pya -p "…"`) is the same minus the input loop: one `user_message`,
one `run_agent`, then exit. Same loop, same renderer — only the driver differs. This is the
payoff of keeping policy and presentation out of `run_agent`.

## Try this

1. Write a 20-line REPL: read a line, append `user_message`, `async for` over `run_agent`,
   call `renderer.handle`. You've rebuilt the core of `app.py`.
2. Add an approver that prints the command and reads `y/a/n` — now mutating tools prompt.
3. Add a fake `/time` command that prints the clock and `continue`s without a model turn.

## Anatomy recap

You assembled the **app** around the **loop**: render the event stream, drive one
`run_agent` per message, and intercept slash commands before they become turns —
plus the interactive **approver** that satisfies the `"ask"` permission from Tutorial 2.
No new agent logic; just presentation and policy wiring. Next: the seams that make long
runs survive contact with reality.

**Next:** [Production seams →](04-production-seams.md)
Reference: [the agent loop](../agent-loop.md) · [commands](../commands.md) · `agent/render.py`, `agent/app.py`, `agent/commands.py`
