# Permissions

Permissions decide whether a tool call may run, modeled on Claude Code. Read-only tools
(`read`/`grep`/`find`/`ls`) always run; mutating tools (`write`/`edit`/`bash`) are gated.
Defined in `agent.permissions`.

## Modes

```bash
uv run pya                                 # default: ask before each mutating tool
uv run pya --permission-mode acceptEdits   # auto-allow write/edit; still ask for bash
uv run pya --permission-mode plan          # deny all mutations (read-only exploration)
uv run pya --yolo                          # bypass: allow everything
```

| mode | mutating tools |
|---|---|
| `default` | ask |
| `acceptEdits` | allow `write`/`edit`, ask `bash` |
| `plan` | deny |
| `bypass` | allow |

## Rules

Beyond the mode, you can set allow/deny rules. A rule is a bare tool name (`"bash"`) or a
name with a glob target — `bash(...)` matches the command, others match the path:

```python
from agent.permissions import Permissions, PermissionMode

Permissions(
    mode=PermissionMode.DEFAULT,
    allow=["bash(git *)", "write(src/*)"],   # auto-allow these
    deny=["bash(rm *)"],                      # never allow these
)
```

Resolution order: **deny rules → mode `bypass` → allow rules → read-only tools → the
mode's default for mutating tools.** Deny always wins; `decide()` returns `"allow"`,
`"deny"`, or `"ask"`.

## Approval

When the decision is `"ask"`, the loop calls an **approver**. The REPL's approver prompts:

```
allow write {"path": "a.py", "content": "..."}? [y/N/a]
```

- `y` — allow once
- `a` — allow always: adds a session allow-rule (for `bash` it's scoped to the command's
  first word, e.g. `bash(npm *)`; for others, the tool name) so you aren't asked again
- `n` — deny (the model gets an error result and adapts)

Approval prompts are serialized even when tools run in parallel, so they never interleave.
In non-interactive use, an approver that can't read input denies by default.

## Programmatic use

The loop is policy-free by default — pass a `Permissions` (and `approver`) to enable
gating:

```python
from agent.loop import run_agent
from agent.permissions import Permissions, PermissionMode

perms = Permissions(mode=PermissionMode.ACCEPT_EDITS, deny=["bash(rm *)"])
async for event in run_agent(model, tools, history, permissions=perms, approver=my_approver):
    ...
```

With no `permissions` argument, every tool call runs — the loop is a mechanism; the app
sets policy. For deeper customization use a [PreToolUse hook](hooks.md), which runs before
the permission check.
