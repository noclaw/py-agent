# py-agent — Plan & Status

A readable, **standalone** Python coding agent — the agent loop, the tools, and the model
layer are all plain Python. The goal is an example implementation that is (a) easy to read
for people learning Python, and (b) a clean starting point for personal-assistant /
second-brain agents.

The shipped feature set deliberately mirrors **Claude Code** (tools, hooks, slash + markdown
commands, permissions, sessions, skills, compaction, auto-retry, and sub-agents) so the
concepts transfer.

---

## Architecture

Everything is in-process Python; the only thing that leaves the process is the HTTPS call
to a model provider.

| Layer | Where | Notes |
|---|---|---|
| **Model / provider / streaming / auth** | `agent/providers/` + `agent/wire.py` | Native over `httpx`: `openai_compat` (OpenAI + local/OpenAI-compatible) and `anthropic` backends; route a transport we don't ship via the `Provider` protocol |
| **Agent loop + harness** | `agent/loop.py` | Turn structure, tool-exec orchestration, gating/retry/compaction seams |
| **Coding product** (tools, system prompt, sessions, commands, skills) | `agent/tools/`, `agent/*.py` | Plain Python |

```
┌─────────────────────────── Python (py-agent) ────────────────────────────┐
│  cli / app / render                                                       │
│  loop  ──>  tools (read/write/edit/bash/grep/find/ls)                     │
│    │        gated by:  hooks → permissions → approval                     │
│    │ per turn: stream(context{system, messages, tools})                  │
│    ▼                                                                      │
│  model.py ──by api──> providers/  (openai_compat · anthropic)            │
└──────────────────────────────────────┼───────────────────────────────────┘
                                        ▼  httpx (SSE)
                          provider HTTP APIs (OpenAI-compatible / Anthropic)
```

The native model layer replaced an earlier out-of-process approach; it now talks to provider
HTTP APIs directly over `httpx` (see the model-layer notes in `CLAUDE.md`).

---

## Status — what's built ✅

Pure-Python dependencies (`httpx`, `pydantic`, `rich`) — no Node, no subprocess. Core phases
complete:

| Phase | Status | Where |
|---|---|---|
| 1. Scaffold (uv, `pya` CLI, src layout) | ✅ | `pyproject.toml`, `src/agent/` |
| 2. Core types (messages, events, `Tool`, converters) | ✅ | `types.py`, `wire.py` |
| 3. Model adapter (`Model`, `ModelLike`, `open_model`) | ✅ | `model.py` |
| 4. Tools — full set read/write/edit/bash/grep/find/ls | ✅ | `tools/` |
| 5. Agent loop (`run_agent`, parallel/sequential exec, gating, cancel) | ✅ | `loop.py` |
| 6. System prompt (programmatic, + project context) | ✅ | `system_prompt.py` |
| 7. CLI / REPL / renderer (one-shot + multi-turn, Ctrl-C abort) | ✅ | `cli.py`, `app.py`, `render.py` |

### Additional features (Claude-Code-shaped) ✅

Beyond the seven core phases, these optional features are also built:

- ✅ **Permissions** — modes (default/acceptEdits/plan/bypass), allow/deny rules
  (`bash(git *)`, `write(src/*)`), interactive y/a/n approval. `permissions.py`.
- ✅ **Hooks** — `PreToolUse` / `PostToolUse` / `UserPromptSubmit` with allow/deny +
  `additional_context`, tool-name matchers, sync/async. `hooks.py`.
- ✅ **Slash commands + custom markdown commands** — built-ins (`/help`, `/clear`,
  `/model`, `/tools`, `/mode`, `/sessions`, `/resume`, `/exit`) and `.pya/commands/*.md`
  with `$ARGUMENTS`/`$1` + frontmatter. `commands.py`.
- ✅ **Sessions** — linear JSONL save/resume per directory; `-c`/`--resume`/`--no-session`.
  `sessions.py`.
- ✅ **Skills** — progressive-disclosure `SKILL.md` under `.pya/skills/<name>/`; name +
  description injected into the system prompt, full file read on demand; `/skills` and
  `/skill:<name>`. `skills.py`.
- ✅ **Compaction** — auto-summarize old history near the context window via a
  `transform_context` seam on the loop. `compaction.py`.
- ✅ **Auto-retry** — re-stream a turn on transient model errors with backoff. `retry.py`.
- ✅ **Sub-agents** — a `task` tool spawning a child `run_agent` with its own budget.
  `tools/task.py`.
- ✅ **`UserPromptSubmit` wiring** — hooks can block/augment a prompt before each turn. `app.py`.
- ✅ **Model registry + selection** — custom/local models via `.pya/models.json`
  (`models_registry.py`), selectable by `--model`/`/model` and listed by `pya models`;
  `/model` with no arg opens a dependency-free fuzzy picker (`picker.py`).
- ✅ **Settings file** — `~/.pya/settings.toml` (`settings.py`): provider API keys (no
  `export`), provider/model scoping + allowlist, a `default` model, and runtime defaults
  (reasoning/permission_mode/max_retries/context_window/compact/subagent). Managed by
  `pya auth set/list/remove` and `pya config show/set/unset/…`.
- ✅ **Native provider layer** (`agent/providers/`) — model calls go directly to provider
  HTTP APIs over httpx (`openai-completions` + `anthropic-messages` backends); `wire.py`
  holds the native message/stream types. No Node, no subprocess. Exotic transports
  (Bedrock/Vertex/Azure) are out of scope — add a `Provider`.
- ✅ **Web tools** — read-only `web_fetch` (URL → readable text) and `web_search` (keyless
  DuckDuckGo) over httpx, in the default `coding_tools` set. `tools/web.py`.
- ✅ **Edit checkpoints / undo** — snapshot a file's bytes before each successful
  `write`/`edit` (via `PreToolUse`/`PostToolUse` hooks); `/checkpoints` lists them and
  `/rewind [N]` restores the working tree. `checkpoints.py`.
- ✅ **Memory / second-brain tools** — `note` (save), `recall` (read recent), and
  `search_memory` (find) over one local markdown store (`~/.pya/memory.md`, override with
  `PYA_MEMORY_FILE`). In the default toolset and as a standalone `memory_tools()` bundle —
  the assistant-repurposing showcase. `tools/memory.py`.
- ✅ **Todo / planning tool** — `todo_write` (Claude Code's `TodoWrite` shape) tracks a
  multi-step plan as a checklist the renderer draws live; mutates *shared run state* (the
  tool's own list), not the filesystem, so it's auto-allowed. `tools/todo.py`.
- ✅ **Persistent permission rules** — allow/deny rules (from "always" approvals or the
  `/permissions` command) are saved to `<cwd>/.pya/permissions.json` and reloaded next
  session. `PermissionStore` in `permissions.py`; `/permissions` in `commands.py`.

**Tests:** ~199 unit (scripted fake-model fixture + `httpx.MockTransport`, no network; the
picker's interactive path runs through a PTY) + a few gated live integration tests
(`PYA_LIVE_LLM=1` + `ANTHROPIC_API_KEY`).

---

## Potential Features (by recommended priority)

Ideas for anyone extending this codebase into their own agent. None are required for the
example to be complete; they're the natural next seams. Roughly ordered by value for the
project's two goals — (a) readable learning example, (b) base for assistant / second-brain
agents.

### 1. Memory / second-brain tools — ✅ shipped

The repurposing showcase: `note`, `recall`, `search_memory` over a local markdown store.
Demonstrates swapping the coding toolset for an assistant toolset via the same registry —
directly serves goal (b). See `tools/memory.py`, the `memory_tools()` bundle, and the
companion [`docs/building-your-own-agent.md`](docs/building-your-own-agent.md). A natural next
step is a sqlite/embeddings backend behind the same three tools.

### 2. Images / vision

Read-tool image attachments + passing image content blocks through to the model (both
provider backends support image input). Mostly plumbing.

### 3. Todo / planning tool — ✅ shipped

A `todo_write` tool (Claude Code's `TodoWrite` shape) the agent uses to track a multi-step
plan, rendered as a live checklist. Demonstrates a tool that mutates *shared run state* (the
tool instance's own list) rather than the filesystem — auto-allowed. See `tools/todo.py` and
the renderer's `_render_todos`.

### 4. Token / cost budget

Enforce a per-run ceiling on tokens (or estimated cost) using the `usage` the renderer
already accumulates: warn near the limit, stop cleanly when exceeded. Pairs with compaction
(`--context-window`) and gives long autonomous runs a guardrail.

### 5. MCP tool servers

Expose external [MCP](https://modelcontextprotocol.io) tools through the same `Tool`
protocol (an adapter that lists remote tools and proxies `execute`). Powerful but heavier
than skills, and less central to the learning/second-brain goals.

### 6. Persistent permission rules — ✅ shipped

Allow/deny rules built up via "always" approvals (or the `/permissions` command) are saved to
`<cwd>/.pya/permissions.json` and reloaded next session, instead of living only in memory for
the current run. See `PermissionStore` + `Permissions.load` in `permissions.py` and
`/permissions` in `commands.py`.

### 7. Polish

Richer TUI (`textual`/`prompt_toolkit`), HTML/markdown transcript export, themes, and
persisting a `compaction` entry into the session JSONL so resumed runs keep the summary.

## Testing strategy

1. **Unit** — tools (temp dirs), prompt assembly, schema validation, message conversion,
   permissions, hooks, commands, sessions.
2. **Loop** — against the **fake-model fixture** (scripted `StreamEvent` turns, no
   network): turn structure, parallel/sequential exec, gating, error/abort, max-turns.
3. **Integration** — a few real runs against a cheap model (Haiku), gated on
   `PI_LIVE_LLM=1`: tool round-trip, an end-to-end file edit, cross-process session resume.
4. **CI** — unit + loop always; integration only when credentials are present.
