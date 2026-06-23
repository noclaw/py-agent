# Hooks

Hooks are callbacks at key points in a run, modeled on Claude Code's hooks but as plain
Python callables (no shell-command/JSON protocol). They're defined in `agent.hooks`.

## Events

| event | when | can… |
|---|---|---|
| `PreToolUse` | before a tool runs | `allow` (skip the permission check) or `deny` (block) it |
| `PostToolUse` | after a tool runs | attach `additional_context` (extra text fed back to the model) |
| `UserPromptSubmit` | the user submits a prompt | `deny` it, or attach `additional_context` |

Each event is a dataclass: `PreToolUse(tool_name, tool_input, tool_call_id)`,
`PostToolUse(..., result)`, `UserPromptSubmit(prompt)`.

A hook returns a `HookResult(decision=None, reason=None, additional_context=None)` — or
`None` for "no opinion". `decision` is `"allow"` / `"deny"`.

## Registering hooks

```python
from agent.hooks import Hooks, HookResult

hooks = Hooks()

@hooks.pre_tool_use(matcher="bash")          # matcher: glob(s) on tool name, e.g. "write|edit"
def block_force_push(event):
    if "push --force" in event.tool_input.get("command", ""):
        return HookResult(decision="deny", reason="no force pushes")

@hooks.post_tool_use(matcher="write|edit")
def remind_to_test(event):
    return HookResult(additional_context="Reminder: run the tests after editing.")

@hooks.user_prompt_submit()
def add_branch(event):
    return HookResult(additional_context="(current branch: main)")
```

Hooks may be sync or async. Register without decorators via
`hooks.add("PreToolUse", fn, matcher=...)`. Multiple hooks for an event run in
registration order; all their results are collected.

Pass them to the loop:

```python
from agent.loop import run_agent
async for event in run_agent(model, tools, history, hooks=hooks, ...):
    ...
```

## Hooks vs permissions

Both gate `PreToolUse`, in this order: **hooks first, then permissions.** A hook that
returns `decision="allow"` short-circuits the permission check; `deny` blocks the call
outright. If no hook has an opinion, the [permission policy](permissions.md) decides
(allow / deny / ask). This lets a hook implement bespoke rules (e.g. block writes outside a
directory) while the permission system handles the general allow/deny/ask flow.

> The REPL does not register `UserPromptSubmit` hooks by default — wiring that in `app.py`
> is a small, documented follow-up (see `PLAN.md`). `PreToolUse`/`PostToolUse` are fully
> wired through the loop.
