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

Whether a tool counts as "read-only", and what string its `tool(glob)` rule matches, come
from the **tool itself** — its `read_only` flag and `permission_target(args)` (see
[Gating a tool](tools.md#gating-a-tool-owns-its-permission-policy)). The loop passes the tool
to `decide()`, so adding or gating a tool needs no edit here. The `READ_ONLY_TOOLS` /
`MUTATING_TOOLS` sets in `permissions.py` are just a name-only fallback for calling `decide()`
without a tool object.

## Approval

When the decision is `"ask"`, the loop calls an **approver**. The REPL's approver prompts:

```
allow write {"path": "a.py", "content": "..."}? [y/N/a]
```

- `y` — allow once
- `a` — allow always: adds an allow-rule (for `bash` it's scoped to the command's first word,
  e.g. `bash(npm *)`; for others, the tool name) so you aren't asked again — and **persists**
  it (see below)
- `n` — deny (the model gets an error result and adapts)

Approval prompts are serialized even when tools run in parallel, so they never interleave.
In non-interactive use, an approver that can't read input denies by default.

## Persistent rules

Allow/deny rules survive across sessions: they're saved to `<cwd>/.pya/permissions.json`
(a small `{"allow": [...], "deny": [...]}` object, alongside the rest of `.pya/`) and reloaded
on startup. An "always" approval writes through automatically, and the **`/permissions`**
command shows and edits them:

```
/permissions                       # show mode + current allow/deny rules
/permissions allow bash(git *)     # add an allow rule (persisted)
/permissions deny  write(secret/*) # add a deny rule (persisted)
/permissions remove bash(git *)    # drop a rule
/permissions reset                 # clear all rules
```

Under the hood, `Permissions.load(cwd, mode=…)` seeds a `Permissions` from the file and keeps
a `PermissionStore` attached so later edits are written back; persistence is best-effort and
never breaks a run.

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
