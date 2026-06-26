# Tools

Tools are how the agent acts. Built-ins live in `src/agent/tools/`:

| tool | purpose |
|---|---|
| `read` | read a file (with `offset`/`limit`, truncation) |
| `write` | create/overwrite a file (makes parent dirs) |
| `edit` | exact-match text replacement (unique match required), returns a diff |
| `bash` | run a shell command (streamed output, timeout, kills the process tree) |
| `grep` | regex search across files (skips VCS/build dirs) |
| `find` | glob for files |
| `ls` | list a directory |
| `web_fetch` | fetch a URL and return its readable text (HTML → plain text) |
| `web_search` | search the web (keyless DuckDuckGo) and return top results |
| `task` | delegate a focused sub-task to a [sub-agent](#sub-agents-the-task-tool) (opt-in) |

Bundles: `coding_tools(cwd)` (the file/shell tools + the two web tools) and
`read_only_tools(cwd)` (read/grep/find/ls). The `task` tool is added separately via
`with_task_tool(...)` because it needs a live model — see [below](#sub-agents-the-task-tool).

The built-in set has one source of truth: the ordered `BUILTIN_TOOL_CLASSES` tuple in
`agent/tools/__init__.py`. `TOOL_CLASSES` (name → class) and `coding_tools()` both derive from
it, so adding a built-in is a one-line append (and a consistency test guards against drift).

### Web tools

`web_fetch(url)` GETs a page and reduces HTML to readable text (text/JSON passes through);
`web_search(query, max_results)` runs a query against a simple **keyless DuckDuckGo HTML**
backend and returns `title / URL / snippet` rows — swap it for a search API (Brave, Tavily,
…) in production. Both use `httpx` and are *read-only* (auto-allowed), but they make outbound
network calls — a `deny` rule can block them by target, e.g.
`Permissions(deny=["web_fetch(*internal*)"])` (web rules match the `url` / `query`).

## Anatomy of a tool

A tool is a subclass of `Tool` (`agent.types`). Parameters are a **Pydantic model**, whose
JSON Schema is what the model sees and what the loop validates arguments against before
calling `execute`.

```python
from pydantic import BaseModel, Field
from agent.types import Tool, ToolResult


class GreetArgs(BaseModel):
    name: str = Field(description="Who to greet")
    enthusiastic: bool = False


class GreetTool(Tool):
    name = "greet"                       # the model calls it by this name
    description = "Greet a person by name."
    parameters = GreetArgs
    prompt_snippet = "greet: Greet a person"   # one line for the system prompt's tool list
    prompt_guidelines = ()               # optional extra guideline bullets
    execution_mode = "parallel"          # or "sequential" to force serialized execution
    read_only = True                     # never mutates the workspace → auto-allowed (default: False)

    async def execute(self, args: GreetArgs, *, on_update=None) -> ToolResult:
        text = f"Hello, {args.name}{'!!!' if args.enthusiastic else '.'}"
        return ToolResult(content=text)
```

`ToolResult(content, details=None, is_error=False)`:
- `content` — text shown to the model.
- `details` — optional structured data for the renderer (the `edit` tool puts a diff here).
- `is_error` — marks a failure; the model sees the content and can react.

### Gating: a tool owns its permission policy

A tool declares how it's gated, so [permissions](permissions.md) never needs a hardcoded list
of tool names:

- **`read_only`** (`ClassVar[bool]`, default `False`) — `True` means the tool never modifies the
  workspace, so it's auto-allowed without a prompt. Set it on read-only tools (`read`, `grep`,
  the web tools); leave it `False` on anything that writes, runs commands, or has side effects.
- **`permission_target(args)`** (classmethod, default `args["path"]`) — the string that a
  `tool(glob)` rule matches against. Override it when the gated argument isn't `path`: `bash`
  returns the command (so `bash(git *)` works), the web tools return the URL/query.

That's all — no edit to `permissions.py` is needed to add or gate a tool. The loop passes the
tool to `Permissions.decide`, which reads these two from the tool itself. (The name-based
`READ_ONLY_TOOLS`/`MUTATING_TOOLS` sets in `permissions.py` are only a fallback for calling
`decide` without a tool object, e.g. in tests, and a consistency test keeps them in sync.)

### Working directory & helpers

Most tools operate on files, so subclass `BaseTool` (`agent.tools.base`) instead — it
takes a `cwd` and gives you `self.resolve(path)` plus truncation helpers:

```python
from agent.tools.base import BaseTool, ToolResult, truncate_head

class HeadTool(BaseTool):
    name = "head"
    description = "Show the first lines of a file."
    parameters = HeadArgs

    async def execute(self, args, *, on_update=None) -> ToolResult:
        path = self.resolve(args.path)          # absolute, relative to cwd
        if not path.exists():
            return ToolResult(content=f"not found: {args.path}", is_error=True)
        text, truncated = truncate_head(path.read_text())
        return ToolResult(content=text)
```

### Streaming output

For long-running tools, call `on_update(chunk)` to stream partial output; the loop turns
each call into a `ToolOutput` event the renderer can show live (this is how `bash`
streams stdout). File I/O should be offloaded with `asyncio.to_thread` so it doesn't block
the loop. Cancellation is cooperative `asyncio` — use `try/finally` to clean up (e.g. kill
a subprocess), as `bash` does.

## Using custom tools

Pass your tools to `run_agent` (any list of `Tool` instances):

```python
from agent.loop import run_agent
from agent.tools import coding_tools

tools = coding_tools(".") + [GreetTool()]
async for event in run_agent(model, tools, history, system_prompt=sp):
    ...
```

Adding a tool automatically updates the system prompt's "Available tools" list and
guidelines (built from each tool's `prompt_snippet`/`prompt_guidelines`). The registry in
`tools/__init__.py` (`TOOL_CLASSES`, the bundle functions) is the seam where you swap the
toolset — see [building your own agent](building-your-own-agent.md).

## Sub-agents: the `task` tool

`task` lets the agent **delegate** a self-contained sub-task to a child agent with its own
toolset and turn budget. The child runs a nested `run_agent` seeded with the caller's
`prompt`, works autonomously, and its final message becomes the tool result — so the parent's
context stays clean of the child's intermediate tool churn. This enables a
"scout → plan → implement" style of delegation.

```python
from agent.tools import coding_tools, with_task_tool

tools = with_task_tool(coding_tools(cwd), model=model, cwd=cwd,
                       permissions=permissions, approver=approver)
```

Arguments the model passes: `description` (a short label) and `prompt` (the full
instructions — the sub-agent can't ask follow-up questions, so give it everything).

Design points (`src/agent/tools/task.py`):

- **No recursion** — the sub-agent's toolset is a fresh `coding_tools(cwd)` *without* a nested
  `task` tool, so delegation can't spiral.
- **Sequential** — `execution_mode = "sequential"`, so the child's model stream never overlaps
  the parent's on the shared client.
- **Budgeted** — the child has its own `max_turns` (default 15), independent of the parent.
- **Gated the same way** — pass `permissions`/`approver` and the sub-agent's mutating calls go
  through the same [gating](permissions.md) as the parent's.
- **Visible** — the child's tool activity is streamed back through `on_update`, so the parent
  renderer shows the sub-agent working.

In the CLI it's on by default; disable with `--no-subagent`.

## How the loop calls a tool

For each tool call the model makes, the loop:
1. emits `ToolStart`,
2. **gates** it ([hooks](hooks.md) → [permissions](permissions.md) → approval),
3. validates the raw arguments against `parameters` (a Pydantic `ValidationError` becomes
   an error result, not a crash),
4. `await tool.execute(args, on_update=...)`,
5. runs [PostToolUse hooks](hooks.md), emits `ToolEnd`, and feeds a `toolResult` back.

A tool that raises is caught and reported to the model as an error result — a buggy tool
won't kill the run.
