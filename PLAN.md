# py-agent — Plan & Status

A Python port of the Pi coding-agent. The **agent loop and tools are written in readable
Python**; the **model / provider / streaming / auth layer is delegated to Pi's
`@earendil-works/pi-ai`** through the `pi-py` SDK. The goal is an example implementation
that is (a) easy to read for people learning Python, and (b) a clean starting point for
personal-assistant / second-brain agents.

The shipped feature set deliberately mirrors **Claude Code** (tools, hooks, slash + markdown
commands, permissions, sessions, skills, compaction, auto-retry, and sub-agents) so the
concepts transfer.

---

## Architecture

Pi is three layered npm packages. Understanding the split is the whole design:

| Layer | npm package | We… |
|---|---|---|
| **Model / provider / streaming / auth** | `@earendil-works/pi-ai` | **Reuse** via a Node shim (don't reimplement) |
| **Generic agent loop + harness** | `@earendil-works/pi-agent-core` | **Ported to Python** (loop, turn structure, tool-exec orchestration) |
| **Coding product** (tools, system prompt, sessions, slash cmds) | `@earendil-works/pi-coding-agent` | **Ported to Python** |

`pi-ai` is the only piece kept as a black box (30+ providers, OAuth, transports, local
models). The loop and tools — the parts worth learning and customizing — are Python.

There is **no Pi mode that streams raw model output without the full agent**, so `pi-py`
gained a small Node shim that imports `pi-ai` and exposes `streamSimple` over JSONL; the
Python loop calls it once per assistant turn.

```
┌─────────────────────────── Python (py-agent) ────────────────────────────┐
│  cli / app / render                                                       │
│  loop  ──>  tools (read/write/edit/bash/grep/find/ls)                     │
│    │        gated by:  hooks → permissions → approval                     │
│    │ per turn: stream(context{system, messages, tools})                  │
│    ▼                                                                      │
│  pi_py_sdk.PiModelClient  ──JSONL──┐                                      │
└──────────────────────────────────────┼───────────────────────────────────┘
                                        ▼
              Node shim  ──imports──>  @earendil-works/pi-ai
              (providers, auth, transports, local models)
```

---

## Status — what's built ✅

**`pi-py` 0.2.0** (published to PyPI) — added `PiModelClient`/`PiModelClientSync` + the
Node shim (`_shim/stream.mjs`) bridging pi-ai's `streamSimple`. `PiAgent` (full-agent RPC
client) left untouched.

**`py-agent`** depends on `pi-py-sdk>=0.2.0` from PyPI. Core phases complete:

| Phase | Status | Where |
|---|---|---|
| 0. pi-py model-streaming client + shim | ✅ | `pi-py` repo |
| 1. Scaffold (uv, `pya` CLI, src layout) | ✅ | `pyproject.toml`, `src/agent/` |
| 2. Core types (messages, events, `Tool`, converters) | ✅ | `types.py` |
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
- ✅ **Native provider layer** (`PROVIDERS.md`, Phases 1–2) — model calls go directly to
  provider HTTP APIs over httpx (`agent/providers/`: `openai-completions` + `anthropic-messages`,
  with Claude Pro/Max OAuth); `wire.py` holds the native types; **`pi_py_sdk` and Node are
  removed**. Exotic transports (Bedrock/Vertex/Azure) are out of scope — add a `Provider`.

**Tests:** ~149 unit (scripted fake-model fixture + `httpx.MockTransport`, no network; the
picker's interactive path runs through a PTY) + a few gated live integration tests
(`PYA_LIVE_LLM=1` + `ANTHROPIC_API_KEY`).

---

## Potential Features (by recommended priority)

Ideas for anyone extending this codebase into their own agent. None are required for the
example to be complete; they're the natural next seams. Roughly ordered by value for the
project's two goals — (a) readable learning example, (b) base for assistant / second-brain
agents.

### 1. Memory / second-brain tools

The repurposing showcase: `note`, `recall`, `search_memory` over a local store (markdown
files or sqlite). Demonstrates swapping the coding toolset for an assistant toolset via the
same registry — directly serves goal (b). Good companion to
[`docs/building-your-own-agent.md`](docs/building-your-own-agent.md).

### 2. Settings file (model registry ✅ · settings ◑ in progress)

The **model registry** shipped — custom/local models in `.pya/models.json`, selectable from
the CLI and the `/model` picker (`models_registry.py`, `picker.py`).

The **settings file** (`~/.pya/settings.toml`, `settings.py`) landed for: provider API keys
(no `export`), scoping which providers/models the catalog offers, a per-provider model
allowlist, and a `default` model. Credential order: spec key → env var → settings.

Still open: management commands (`pya auth set/list`, `pya config`); moving permission-mode
and retry/compaction tuning into settings; inferring `--context-window` per model (the
catalog/registry carry `contextWindow`) instead of the hard-coded flag.

### 3. Images / vision

Read-tool image attachments + passing `ImageContent` through to the model (pi-ai already
supports it). Mostly plumbing.

### 4. Web tools (`web_fetch` / `web_search`)

Fetch a URL (to markdown) and run a search query, as ordinary `Tool` subclasses. Central to
assistant/second-brain use cases and an easy, self-contained read for the tools chapter.

### 5. Todo / planning tool

A `todo` tool (Claude Code's `TodoWrite` shape) the agent uses to track a multi-step plan,
rendered as a checklist. Improves long-task behavior and demonstrates a tool that mutates
*shared run state* rather than the filesystem.

### 6. Token / cost budget

Enforce a per-run ceiling on tokens (or estimated cost) using the `usage` the renderer
already accumulates: warn near the limit, stop cleanly when exceeded. Pairs with compaction
(`--context-window`) and gives long autonomous runs a guardrail.

### 7. MCP tool servers

Expose external [MCP](https://modelcontextprotocol.io) tools through the same `Tool`
protocol (an adapter that lists remote tools and proxies `execute`). Powerful but heavier
than skills, and less central to the learning/second-brain goals.

### 8. Edit checkpoints / undo

Snapshot file state before each `write`/`edit` (a shadow copy or a scratch git stash) so a
session can rewind, à la Claude Code's checkpoint/rewind. Pairs with sessions and makes
`--yolo` runs safer to experiment with.

### 9. Persistent permission rules

Save the allow/deny rules built up via the "always" approval to `.pya/` so they carry across
sessions, instead of living only in memory for the current run (`permissions.py`).

### 10. Polish

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
