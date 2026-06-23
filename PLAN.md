# py-agent — Plan & Status

A Python port of the Pi coding-agent. The **agent loop and tools are written in readable
Python**; the **model / provider / streaming / auth layer is delegated to Pi's
`@earendil-works/pi-ai`** through the `pi-py` SDK. The goal is an example implementation
that is (a) easy to read for people learning Python, and (b) a clean starting point for
personal-assistant / second-brain agents.

The shipped feature set deliberately mirrors **Claude Code** (tools, hooks, slash + markdown
commands, permissions, sessions, and — planned — skills) so the concepts transfer.

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

**Optional features already done** (Claude-Code-shaped):

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

**Tests:** ~90 unit (driven by a scripted fake-model fixture, no network) + a few gated
live integration tests (`PI_LIVE_LLM=1`).

---

## Remaining / optional phases (by recommended priority)

### Skills ✅ *(done — `skills.py`)*

Implemented as designed below. Skills let you teach the agent workflows and knowledge with
**plain markdown**, no servers or protocol — they differ from slash commands
(user-invoked): skills are *model-aware* via **progressive disclosure** — only each skill's
name + description sits in the system prompt, and the model reads the full `SKILL.md` (with
the `read` tool) when a task matches.

Design (`skills.py`):
- **Discovery:** `~/.pya/skills/<name>/SKILL.md` (user) and `<cwd>/.pya/skills/<name>/SKILL.md`
  (project). Frontmatter `name`, `description`; the body is instructions and may reference
  sibling files/scripts in the skill directory.
- **Prompt integration:** extend `build_system_prompt(..., skills=...)` to emit an
  `<available_skills>` block of `{name, description, path}` (mirrors Pi's
  `formatSkillsForSystemPrompt`). The model reads the path on demand.
- **Optional UX:** a `/skills` command to list them, and `/skill:<name>` to invoke one
  directly (like Pi's `enableSkillCommands`).
- **Tests:** loader (frontmatter parse, discovery, precedence project>user), prompt block
  assembly; live: a skill whose description triggers the model to read it and follow it.
- Port reference: `packages/agent/src/harness/skills.ts`,
  `packages/coding-agent/.../skills.ts`.

### 2. Compaction

Auto-summarize when the conversation nears the model's context window. Implement as a
`transform_context` hook on the loop (add that seam to `run_agent`), so it's optional and
swappable. A simple "summarize the oldest turns, keep the most recent K tokens" is enough
to demonstrate; Pi's branch summarization is advanced. Pairs naturally with sessions
(persist a `compaction` entry). Port: `packages/agent/src/harness/compaction/`.

### 3. Memory / second-brain tools

The repurposing showcase: `note`, `recall`, `search_memory` over a local store
(markdown files or sqlite). Demonstrates swapping the coding toolset for an assistant
toolset via the same registry — directly serves goal (b). Good companion to a
`docs/building-your-own-agent.md`.

### 4. `UserPromptSubmit` hook wired into the REPL  *(small)*

The loop already supports `UserPromptSubmit`; wire it in `app.py` so a hook can block a
prompt or inject context before a turn (e.g. add the current git branch, redact secrets).

### 5. Images / vision

Read-tool image attachments + passing `ImageContent` through to the model (pi-ai already
supports it). Mostly plumbing.

### 6. Sub-agents / Task tool

A `Task` tool that spawns a child `run_agent` with a restricted toolset and its own
budget, returning a summary. Enables "scout → plan → implement" style delegation.

### 7. Auto-retry

Wrap a turn in a retry policy for transient model errors (pi-ai surfaces these as a
terminal `error` event, so it's a clean wrapper). Pi has `retry.enabled/maxRetries`.

### 8. MCP tool servers  *(lower priority than Skills)*

Expose external [MCP](https://modelcontextprotocol.io) tools through the same `Tool`
protocol (an adapter that lists remote tools and proxies `execute`). Powerful but heavier
than skills, and less central to the learning/second-brain goals — hence after Skills.

### 9. Polish

Richer TUI (`textual`/`prompt_toolkit`), HTML/markdown transcript export, themes.

---

## Documentation — proposed `docs/` folder

The repo *is* the example, so docs should explain the design and the extension seams (how
to add tools/hooks/commands/skills and how to repurpose the agent), not restate the code.
Suggested files (✅ = ready to write now; ⏳ = after the feature lands):

| File | What it documents |
|---|---|
| `docs/README.md` ✅ | Index/table of contents for the docs. |
| `docs/architecture.md` ✅ | The pi-ai / pi-agent-core / pi-coding-agent split, the Node shim, the layering diagram, and the turn lifecycle (stream → tool calls → gate → execute → feed back). The "why" behind delegating only the model call. |
| `docs/getting-started.md` ✅ | Install, Node + `pi` requirement, credentials (provider env var **or** `pi` OAuth login), first run, one-shot vs REPL. |
| `docs/tools.md` ✅ | The built-in tools, and **how to write a custom tool**: Pydantic params → JSON Schema, `execute`, `ToolResult`, streaming via `on_update`, `execution_mode`, registering via a bundle. The key extension seam. |
| `docs/permissions.md` ✅ | Modes, rule syntax (`tool`, `tool(glob)`), the approval flow, `allow_always`, and programmatic use of `Permissions`. |
| `docs/hooks.md` ✅ | Events, decisions, matchers; worked examples (block dangerous bash, post-tool lint feedback, prompt-context injection). |
| `docs/commands.md` ✅ | Built-in slash commands + authoring custom markdown commands (frontmatter, `$ARGUMENTS`/`$1`, namespacing). |
| `docs/sessions.md` ✅ | The JSONL format, storage location (`PYA_SESSIONS_DIR`), per-cwd resume, and the linear-log-vs-Pi-tree tradeoff. |
| `docs/models-and-providers.md` ✅ | How the model layer works via pi-py/pi-ai, the credential-resolution order, switching models (`/model`), and configuring custom/local models (Ollama, LM Studio) via `models.json`. |
| `docs/configuration.md` ✅ | All env vars (`PYA_SESSIONS_DIR`, `PI_AI_DIR`, `PI_NODE`, provider keys), defaults, and `.pya/` directory layout (commands, skills). |
| `docs/agent-loop.md` ✅ | A guided read of `loop.py` for learners/contributors: the event queue, turns, gating, parallel/sequential execution, cancellation. |
| `docs/building-your-own-agent.md` ✅ | The repurposing guide: drive `run_agent` programmatically, swap the toolset, build a second-brain/personal assistant. The headline "starting point" doc. |
| `docs/skills.md` ✅ | Authoring `SKILL.md`, discovery, progressive disclosure, `/skills` & `/skill:<name>`. |
| `docs/development.md` ✅ | Project layout, running tests (unit vs `-m integration`, `PI_LIVE_LLM`), the optional local-pi-py path dependency, conventions. |

(Several of these overlap with README sections; the README stays a quick tour and links
into `docs/` for depth.)

## `examples/` folder

**Recommendation: drop it.** The whole repo is the worked example, the README has runnable
commands, and the extension docs above carry focused snippets (custom tool, hook, command,
skill, programmatic `run_agent`). A separate `examples/` of scripts would duplicate those
and drift. The empty `examples/` directory has been removed. If we later want runnable
end-to-end demos, prefer a single `docs/building-your-own-agent.md` with copy-pasteable
code over a scripts folder.

---

## Testing strategy

1. **Unit** — tools (temp dirs), prompt assembly, schema validation, message conversion,
   permissions, hooks, commands, sessions.
2. **Loop** — against the **fake-model fixture** (scripted `StreamEvent` turns, no
   network): turn structure, parallel/sequential exec, gating, error/abort, max-turns.
3. **Integration** — a few real runs against a cheap model (Haiku), gated on
   `PI_LIVE_LLM=1`: tool round-trip, an end-to-end file edit, cross-process session resume.
4. **CI** — unit + loop always; integration only when credentials are present.
