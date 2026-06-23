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

Bundles: `coding_tools(cwd)` (all seven) and `read_only_tools(cwd)` (read/grep/find/ls).

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

    async def execute(self, args: GreetArgs, *, on_update=None) -> ToolResult:
        text = f"Hello, {args.name}{'!!!' if args.enthusiastic else '.'}"
        return ToolResult(content=text)
```

`ToolResult(content, details=None, is_error=False)`:
- `content` — text shown to the model.
- `details` — optional structured data for the renderer (the `edit` tool puts a diff here).
- `is_error` — marks a failure; the model sees the content and can react.

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
