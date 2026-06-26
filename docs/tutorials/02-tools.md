# 2. Adding tools you can trust

**Parts:** tools (3) · policy seams (5)

In Tutorial 1 a tool was a black box: the model named one, we validated its arguments and
called `.execute()`. Now we build a tool properly, and then answer the question that
matters the moment a tool can *change* things: **how do you stop it from doing the wrong
one?**

## A tool is four things

Every tool is a `Tool` subclass (`agent/types.py`) declaring four pieces:

```python
from pydantic import BaseModel, Field
from agent.types import Tool, ToolResult

class WordCountArgs(BaseModel):                       # 2. parameters (→ JSON Schema)
    path: str = Field(description="File to count words in, relative to the cwd.")

class WordCountTool(Tool):
    name = "word_count"                               # 1. name the model calls
    description = "Count the words in a text file."   # 3. what it's for (the model reads this)
    parameters = WordCountArgs

    async def execute(self, args: WordCountArgs, *, on_update=None) -> ToolResult:  # 4. the work
        text = open(args.path).read()
        return ToolResult(content=f"{len(text.split())} words")
```

The important idea: **the parameter model is the contract.** `parameters` is a Pydantic
model, and `Tool.json_schema()` turns it into the JSON Schema the model sees — so the field
names and `Field(description=...)` you write *are* the API the model codes against. The loop
validates the model's raw arguments against that schema before `execute` ever runs
(`tool.parameters.model_validate(...)`), so by the time you have `args`, it's well-typed.
A `ToolResult.content` string is what the model reads next turn; `is_error=True` tells it
the call failed without aborting the run.

Two optional class attributes shape behavior:

- `prompt_snippet` — the one-line "Available tools" entry in the system prompt.
- `execution_mode = "sequential"` — opt out of parallel execution when a tool can't safely
  overlap with others (e.g. an interactive shell).

Most file tools subclass `BaseTool` (`agent/tools/base.py`) instead of `Tool` directly — it
adds a `cwd` and a `self.resolve(path)` helper so paths stay inside the working directory.
Compare your toy above to the real `agent/tools/read.py`, which uses `resolve`, reads off
the event loop with `asyncio.to_thread`, and truncates large output. Same four pieces, more
care. The full protocol is in [tools](../tools.md).

## Read-only vs mutating — the line that matters

`word_count` and `read` only *observe*. `write`, `edit`, and `bash` *change the world*. The
agent loop runs whatever the model asks unless something says no — so the safety model
isn't in the tool, it's in a **gate** the loop consults before calling `execute`. That gate
is the first of the policy seams (part 5), and it's why policy lives in the app layer, not
the loop.

py-agent splits tools into two sets (`agent/permissions.py`):

```python
READ_ONLY_TOOLS = {"read", "grep", "find", "ls"}     # always allowed
MUTATING_TOOLS  = {"write", "edit", "bash"}           # gated
```

## Permissions: allow / deny / ask

`Permissions.decide(tool_name, args)` returns `"allow"`, `"deny"`, or `"ask"`, in this
priority order:

1. **deny rules** win over everything (a hard "never");
2. **bypass mode** allows everything (`--yolo`);
3. **allow rules** match;
4. **read-only tools** are always allowed;
5. otherwise the **mode** decides for mutating tools.

The modes mirror Claude Code: `default` (ask), `acceptEdits` (auto-allow write/edit, still
ask for bash), `plan` (deny all mutations — read-only exploration), `bypass` (allow all).

Rules are strings: a bare name (`"bash"`) or a glob target — `"bash(git *)"` matches by
command, `"write(src/*)"` matches by path. So you can pre-authorize the safe and forbid the
dangerous up front:

```python
from agent.permissions import Permissions, PermissionMode

perms = Permissions(
    mode=PermissionMode.DEFAULT,
    allow=["bash(git status)", "bash(git diff *)"],   # never prompt for these
    deny=["bash(rm *)", "write(/etc/*)"],             # never allow these
)
perms.decide("bash", {"command": "git status"})  # "allow"
perms.decide("bash", {"command": "rm -rf /"})     # "deny"
perms.decide("bash", {"command": "npm install"})  # "ask"
```

## Wiring the gate into the loop

`run_agent` consults permissions, and when the decision is `"ask"` it calls an **approver**
you provide — that's how the REPL prompts `y/a/n`. When the user answers "always", the loop
calls `permissions.allow_always(...)`, which adds a session allow-rule (scoping `bash` to
its first word) so the same kind of call won't prompt again:

```python
async def approver(tool_name, args, reason):
    answer = input(f"Allow {tool_name} {args}? [y/a/n] ")
    return {"y": "once", "a": "always", "n": "deny"}.get(answer, "deny")

async for event in run_agent(model, tools, history, permissions=perms, approver=approver):
    ...
```

If you pass **no** `permissions`, every call runs — the *library* default is permissive,
and the *app* (Tutorial 3) is what sets a safe policy. That separation is deliberate:
`run_agent` stays mechanism; the app owns policy.

## Try this

1. Add `word_count` to the toy agent from Tutorial 1 and ask the model to use it.
2. Give it `permissions=Permissions(mode=PermissionMode.PLAN)` and watch a `write` request
   come back denied — read-only exploration with no prompts.
3. Add `deny=["bash(git push *)"]` and confirm a push is blocked even in `bypass` mode
   (deny always wins).

## Anatomy recap

You built a **tool** (part 3) — name, typed parameters, description, `execute` — and met
the first **policy seam** (part 5): permissions decide allow/deny/ask *before* the loop runs
a tool, with an approver for the interactive case. The loop provides the hook; the app
provides the policy. Next we assemble the app itself.

**Next:** [Making it interactive →](03-interactive.md)
Reference: [tools](../tools.md) · [permissions](../permissions.md) · `agent/permissions.py`, `agent/tools/base.py`
