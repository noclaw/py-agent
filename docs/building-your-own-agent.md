# Building your own agent

py-agent is a coding agent, but it's structured so the coding parts are swappable. This is
the "starting point for a personal assistant / second-brain" path. The pieces you compose:

- a **model** (`open_model`),
- a list of **tools** (your own `Tool` subclasses, or the built-in bundles),
- a **system prompt** (`build_system_prompt`, or your own string),
- the **loop** (`run_agent`), which yields events you render however you like.

Everything else — permissions, hooks, sessions, commands, skills — is optional and passed
in.

## Drive the loop programmatically

```python
import asyncio
from agent.loop import run_agent
from agent.model import open_model
from agent.system_prompt import build_system_prompt
from agent.tools import coding_tools
from agent.types import user_message, AssistantDone, ToolEnd

async def main():
    cwd = "."
    tools = coding_tools(cwd)
    sp = build_system_prompt(tools, cwd)
    history = [user_message("List the Python files and count them.")]
    async with open_model(provider="anthropic", model="claude-sonnet-4-6") as model:
        async for event in run_agent(model, tools, history, system_prompt=sp):
            if isinstance(event, ToolEnd):
                print("tool:", event.tool_name, "→", event.result.content[:60])
            elif isinstance(event, AssistantDone):
                print("assistant:", event.message)

asyncio.run(main())
```

That's the whole embedding API. Add `permissions=`, `approver=`, `hooks=` to gate or
observe tool use; the loop is permissive by default. Two more optional keywords harden longer
runs: `retry=RetryPolicy(...)` re-streams a turn on transient model errors
([auto-retry](agent-loop.md#auto-retry)), and `transform_context=Compactor(model, ...).transform`
summarizes old history as it nears the context window ([compaction](agent-loop.md#compaction)).
To let your agent delegate, wrap the toolset with
[`with_task_tool`](tools.md#sub-agents-the-task-tool).

## Swap the toolset (a second-brain example)

Replace the coding tools with your own. Tools are just `Tool` subclasses with a Pydantic
parameter model (see [tools](tools.md)). A minimal note store:

```python
from pathlib import Path
from pydantic import BaseModel, Field
from agent.types import Tool, ToolResult

NOTES = Path.home() / ".my-brain" / "notes.md"

class NoteArgs(BaseModel):
    text: str = Field(description="The note to remember")

class NoteTool(Tool):
    name = "note"
    description = "Save a note to the user's second brain."
    parameters = NoteArgs
    prompt_snippet = "note: Save a note"

    async def execute(self, args, *, on_update=None) -> ToolResult:
        NOTES.parent.mkdir(parents=True, exist_ok=True)
        with NOTES.open("a") as fh:
            fh.write(f"- {args.text}\n")
        return ToolResult(content="saved")

class RecallArgs(BaseModel):
    query: str = Field(description="What to search notes for")

class RecallTool(Tool):
    name = "recall"
    description = "Search the user's saved notes."
    parameters = RecallArgs
    prompt_snippet = "recall: Search saved notes"

    async def execute(self, args, *, on_update=None) -> ToolResult:
        if not NOTES.exists():
            return ToolResult(content="(no notes yet)")
        hits = [l for l in NOTES.read_text().splitlines() if args.query.lower() in l.lower()]
        return ToolResult(content="\n".join(hits) or "(no matches)")
```

Then build an assistant instead of a coder:

```python
tools = [NoteTool(), RecallTool()]
sp = build_system_prompt(
    tools, cwd,
    custom="You are a helpful personal assistant and second brain. Save and recall notes.",
)
history = [user_message("Remember that my passport expires in March, then confirm.")]
async with open_model(provider="anthropic", model="claude-sonnet-4-6") as model:
    async for event in run_agent(model, tools, history, system_prompt=sp):
        ...
```

The same loop, prompt builder, permissions, hooks, sessions, and skills all work
unchanged — you only changed the tools and the persona.

## Make it a CLI

The thinnest path to a custom binary is to copy the pattern in `agent/app.py` (build the
prompt, `open_model`, loop, render) and `agent/cli.py` (argument parsing), or add a
`[project.scripts]` entry pointing at your own `main`. For richer behavior, reuse the
[command registry](commands.md) and [skills](skills.md) — drop `.pya/commands/*.md` and
`.pya/skills/*/SKILL.md` next to your project and they're picked up automatically.

## Where to look

- [Tools](tools.md) — the tool protocol in full.
- [The agent loop](agent-loop.md) — what `run_agent` does and the events it emits.
- [Hooks](hooks.md) / [Permissions](permissions.md) — gate and observe tool use.
