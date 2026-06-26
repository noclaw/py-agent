# 5. Make it your own

**Parts:** tools (3) · context/history (4) · policy seams (5)

The whole point of reading the loop instead of importing a framework is that you can now
build a *different* agent. py-agent ships as a coding agent, but nothing in the loop is
about code — that lives entirely in the toolset and the system prompt. This capstone turns
the coder into a personal assistant / second brain, reusing every part you've learned.

## What actually changes

Hold the five parts up against "a second-brain assistant" and notice how little moves:

| Part | Coding agent | Your assistant | Changed? |
|---|---|---|---|
| Model adapter | `open_model(...)` | same | no |
| The loop | `run_agent(...)` | same | no |
| Tools | read/write/edit/bash/grep/find/ls | `note`, `recall`, your APIs | **yes** |
| Context/history | message list + `to_llm_messages` | same | no |
| Policy seams | permissions/hooks/sessions/… | same (maybe different rules) | mostly no |

You change the **tools** and the **persona** (the system prompt). That's the surface area
of a new agent. Everything else — streaming, tool dispatch, permissions, sessions,
compaction, retry, sub-agents — comes along unchanged.

## 1. Decide the tools

Tools *are* your agent's capabilities; pick them before anything else. For a second brain:
`note` (save a thought), `recall` (search saved notes), maybe `today` (fetch the calendar),
`web` (look something up). Each is the four-piece `Tool` from Tutorial 2 — a name, a
Pydantic parameter model, a description the model reads, and an `execute` that does the
work and returns text.

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
```

(A matching `RecallTool` that greps `NOTES` is in
[building your own agent](../building-your-own-agent.md), which is the reference for this
whole tutorial.) The descriptions matter as much as the code: they're the API the model
programs against, so write them like you're documenting a function for a careful colleague.

## 2. Set the persona

The system prompt is the agent's character and standing instructions. `build_system_prompt`
assembles the tool list and guidelines; pass `custom=` to set the persona:

```python
from agent.system_prompt import build_system_prompt

tools = [NoteTool(), RecallTool()]
sp = build_system_prompt(
    tools, cwd,
    custom="You are a calm personal assistant and second brain. "
           "Save what the user wants remembered; recall it when asked.",
)
```

## 3. Reuse the loop verbatim

This is the part you don't write:

```python
from agent.loop import run_agent
from agent.model import open_model
from agent.types import user_message

history = [user_message("Remember my passport expires in March, then confirm.")]
async with open_model(provider="anthropic", model="claude-sonnet-4-6") as model:
    async for event in run_agent(model, tools, history, system_prompt=sp):
        ...   # render however you like — Tutorial 3's Renderer works as-is
```

## 4. Choose your seams

The policy seams from Tutorial 4 are all still available — you just opt into the ones that
fit. An assistant probably wants:

- **Sessions** so it remembers across runs (it's the same JSONL persistence).
- **Compaction** for long-running chats (same `transform_context` seam).
- **Permissions** tuned to *your* tools — each tool declares its own gating, so a custom
  toolset needs no change to `permissions.py`. `recall` only reads, so set `read_only = True`
  on its class and it's auto-allowed; `note` and a `send_email` tool leave the default
  (`read_only = False`) and are gated, asked before they run. (If the gated argument isn't
  `path`, override `permission_target` so rules like `send_email(*@work.com)` match the right
  field — see [tools › gating](../tools.md#gating-a-tool-owns-its-permission-policy).)
- **Sub-agents** if a request fans out ("summarize all my notes from last week").

Nothing here is new machinery — it's the same seams pointed at different tools.

## 5. Package it

The thinnest custom binary copies the shape of `agent/app.py` (build prompt → `open_model`
→ `run_agent` → render) and `agent/cli.py` (argument parsing), then adds a
`[project.scripts]` entry pointing at your own `main`. You can even reuse the command and
skill registries unchanged — drop `.pya/commands/*.md` and `.pya/skills/*/SKILL.md` beside
your project and they're discovered automatically. See
[building your own agent › make it a CLI](../building-your-own-agent.md#make-it-a-cli).

## Where to go from here

You've seen every part of an agent and built one that isn't the one you started with. Good
next steps:

- Give a tool **streaming output** via the `on_update` callback (like `bash`) for long
  operations.
- Add a real data source — a tool that calls an HTTP API, a database, your calendar.
- Write a **skill** ([skills](../skills.md)) so the model learns a workflow from markdown
  instead of code.
- Read `PLAN.md` for the roadmap (memory tools, images, MCP) — and consider which seam each
  would attach to.

## Anatomy recap

The capstone proved the thesis of the whole track: an agent is **model + loop +
context** (fixed) plus **tools + persona + chosen seams** (yours). Change the last three and
you have a new agent without touching the first three. That's the entire idea — and now
it's yours to extend.

Reference: [building your own agent](../building-your-own-agent.md) · [tools](../tools.md) · [skills](../skills.md)
