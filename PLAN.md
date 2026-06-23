# py-agent — Implementation Plan

A Python port of the Pi coding-agent. The **agent loop and tools are written in
readable Python**; the **model/provider/streaming/auth layer is delegated to Pi's
`@earendil-works/pi-ai`** through an extended `pi-py` SDK. The goal is an example
implementation that is (a) easy to read for people learning Python, and (b) a clean
starting point for personal-assistant / second-brain agents.

---

## 0. Architecture & the key decision

Pi is three layered npm packages. Understanding the split is the whole design:

| Layer | npm package | Repo path | We... |
|---|---|---|---|
| **Model / provider / streaming / auth** | `@earendil-works/pi-ai` | `packages/ai` | **Reuse** via a Node shim (don't reimplement) |
| **Generic agent loop + harness** | `@earendil-works/pi-agent-core` | `packages/agent` | **Port to Python** (the loop, turn structure, tool-exec orchestration, compaction & session primitives) |
| **Coding product** (7 tools, system prompt, sessions, slash cmds, config) | `@earendil-works/pi-coding-agent` | `packages/coding-agent` | **Port to Python** (the concrete tools + prompt + app) |

So: `pi-ai` is the only piece we keep as a black box, because it carries 30+
providers, OAuth, transports, and local-model support we don't want to rewrite. The
loop and tools — the parts worth learning and customizing — become Python.

### Why a Node shim is required

`pi-py` today spawns `pi --mode rpc`, which runs the **entire** agent (loop + tools +
sessions). There is **no Pi mode or CLI that streams raw model output without the
agent loop**. So to get "just the model call" into Python we add a small Node script
that imports `pi-ai` and exposes its `streamSimple` over stdin/stdout JSONL. The
Python loop calls that shim once per assistant turn.

```
┌─────────────────────────── Python (this repo) ───────────────────────────┐
│  CLI / REPL / renderer                                                     │
│  Agent loop  ──calls──>  Tools (read/write/edit/bash/grep/find/ls)         │
│       │                                                                    │
│       │ per turn: stream(model, context{system,messages,tools}, options)   │
│       ▼                                                                    │
│  pi_py_sdk.PiModelClient  ──JSONL over stdin/stdout──┐                     │
└──────────────────────────────────────────────────────┼────────────────────┘
                                                        ▼
                         Node shim  ──imports──>  @earendil-works/pi-ai
                         (streamSimple → providers, auth, transports, local)
```

`pi-py`'s existing `PiAgent` (full-agent RPC client) stays **untouched**; we add a new
sibling low-level client. The generic `Transport` (subprocess + JSONL framing) is
already reusable.

---

## Phase 0 — Extend pi-py with a model-streaming client  *(prerequisite, lives in `/Users/jeff/code/pi-py`)*

**0.1 Node shim** — `pi_py_sdk/_shim/stream.mjs`
- Imports the modern, non-deprecated API: `builtinModels()` / `createModels()` and
  `Models.streamSimple` (avoid the `/compat` entrypoint — its header says it's
  temporary). Source pattern to mirror: `packages/coding-agent/src/core/sdk.ts`.
- Reads JSONL requests from stdin, one per line:
  - `{type:"stream", id, model:{provider,id} | <full Model object>, context:{systemPrompt, messages, tools}, options:{reasoning, apiKey, temperature, maxTokens, signal-via-abort, ...}}`
  - `{type:"abort", id}` — cancel an in-flight stream (maps to an `AbortController`).
  - `{type:"list_models"}` — return the resolved catalog (built-ins + any custom).
- For each `AssistantMessageEvent` from the stream, writes
  `{type:"stream_event", id, event}`; on completion `{type:"stream_done", id, message}`;
  on failure `{type:"stream_error", id, message}` (pi-ai surfaces errors as a terminal
  event, not a throw). Every event already carries `partial`/`message`, so Python
  needs **no delta-accumulation logic**.
- **Packaging decision (pick one, document it):**
  1. *Resolve `pi-ai` from the existing `pi` install* (npx fallback already pulls
     `@earendil-works/pi-coding-agent`, which bundles `pi-ai`). Lowest friction.
  2. *Pin a tiny vendored `package.json`* next to the shim and `npm i` on first run.
  3. *`npx --yes @earendil-works/pi-ai@<pinned>`* with the shim passed in.
  Recommend **#1** for parity with current `_discovery.py` behavior, falling back to
  #2 if `pi-ai` isn't resolvable.

**0.2 Python streaming client** — `pi_py_sdk/model.py`
- `class PiModelClient` reusing `Transport` with `argv = [node, <shim path>]`.
  - `async def stream(self, model, context, *, reasoning=None, **options) -> AsyncIterator[StreamEvent]`
    — assigns an `id`, routes incoming `stream_event` lines for that `id` to a queue,
    ends on `stream_done`/`stream_error`. Supports concurrent streams by `id`.
  - `async def complete(self, model, context, **opts) -> AssistantMessage` — convenience
    that drains the stream and returns the final message.
  - `async def list_models(self) -> list[ModelInfo]`.
  - `async def abort(self, id)`.
  - lifecycle: `start`/`stop`/async-context-manager, mirroring `PiAgent`.
- `class PiModelClientSync` — blocking facade (mirror existing `sync.py`).

**0.3 Pydantic types** — extend `pi_py_sdk/protocol.py` (reuse `TextContent`,
`ThinkingContent`, `ImageContent`, `ToolCall` which already exist):
- `Context`, `Message` (`UserMessage`/`AssistantMessage`/`ToolResultMessage`),
  `Tool` (`{name, description, parameters}`), `Usage`, `Model`/`ModelInfo`.
- The streaming event union (`start`, `text_start/delta/end`,
  `thinking_start/delta/end`, `toolcall_start/delta/end`, `done`, `error`) — discriminated
  on `type`.

**0.4 Tests (pi-py side):** unit-test the shim protocol with a fake stdin/stdout;
integration test a real one-line `stream` against a cheap model (e.g. Haiku) guarded
by an env-var/API-key check; test `list_models`; test abort.

**Deliverable:** `pi-py` gains `PiModelClient` while keeping `PiAgent` intact, and a
new minor version is tagged so this repo can depend on it.

---

## Phase 1 — Project scaffolding  *(this repo)*

- `pyproject.toml` (uv-managed, matching pi-py conventions): package name
  `coding_agent` (CLI `pycoda` or similar), Python ≥3.11.
- Dependencies: `pi-py` (the extended SDK), `pydantic>=2`, and a light CLI/render
  layer (`rich` or `prompt_toolkit` — see Phase 7).
- Layout (mirrors the Pi module boundary so readers can cross-reference):
  ```
  src/coding_agent/
    __init__.py
    cli.py            # entry point, arg parsing            (← coding-agent/src/cli)
    app.py            # REPL + one-shot run modes
    loop.py           # the agent loop                      (← agent/src/agent-loop.ts)
    types.py          # AgentMessage, events, tool types    (← agent/src/types.ts)
    model.py          # thin adapter over pi_py_sdk.PiModelClient + registry
    system_prompt.py  # buildSystemPrompt                   (← coding-agent/.../system-prompt.ts)
    config.py         # settings load/merge                 (← coding-agent/src/config.ts)
    render.py         # event → terminal rendering
    tools/
      __init__.py     # registry + bundles                 (← coding-agent/.../tools/index.ts)
      base.py         # Tool protocol, schema, truncation
      read.py write.py edit.py bash.py grep.py find.py ls.py
  tests/
  examples/
  docs/
  ```
- README + CLAUDE.md with the architecture diagram above.

---

## Phase 2 — Core types  *(port `packages/agent/src/types.ts`)*

- `AgentMessage` (the persisted/in-context message: user / assistant / toolResult,
  with model + usage metadata) vs the LLM-wire `Message` from pi-py. Keep the two
  distinct, with a `to_llm_messages()` converter (= Pi's `convertToLlm`).
- Content blocks: text / thinking / image / toolCall (reuse pi-py's).
- Agent event taxonomy to emit from the loop: `agent_start`, `turn_start`,
  `message_start/update/end`, `tool_execution_start/update/end`, `turn_end`,
  `agent_end`. Keep names identical to Pi for familiarity.
- `Tool` protocol: `name`, `label`, `description`, `prompt_snippet`,
  `prompt_guidelines`, `parameters` (JSON Schema), `execute(call_id, args, signal, on_update) -> ToolResult`,
  optional `prepare_arguments`, `execution_mode` ("parallel"|"sequential").

**Schema choice:** Pi uses TypeBox. In Python, define tool parameters as Pydantic
models and emit JSON Schema via `.model_json_schema()` — readable and gives free
validation/coercion (Pi's `validateToolArguments` equivalent).

---

## Phase 3 — Model adapter  *(thin)*

- `model.py` wraps `pi_py_sdk.PiModelClient`: resolve a model spec (provider/id),
  expose `stream(context, tools, reasoning)` returning the typed event stream.
- A minimal **model registry / config** ported from `model-registry.ts`: read an
  optional `models.json` to define custom/local models (Ollama, LM Studio) as full
  `Model` objects with `baseUrl` + `api`. pi-ai handles the rest. Document the
  credential-resolution order (explicit key → env var → ambient) — all handled by
  pi-ai, nothing to implement in Python beyond passing an optional `apiKey`.

---

## Phase 4 — Tools  *(port `packages/coding-agent/src/core/tools/`)*

Implement the default coding set first: **read, write, edit, bash** (Pi's
`createCodingToolDefinitions`), then **grep, find, ls** (the read-only extras).

Per-tool notes (schemas + behaviors to match):
- **read** — `path`, `offset?`, `limit?`; head-truncate to a max line/byte budget;
  image support optional (defer base64/image attachments to an optional phase).
- **write** — `path`, `content`; create parent dirs; "new files or full rewrites only".
- **edit** — `path`, `edits: [{oldText,newText}]`; each `oldText` must match a unique
  region of the **original** file; handle CRLF/LF/BOM; return a diff in `details`.
  Include the `prepare_arguments` shim that tolerates `edits` sent as a JSON string.
- **bash** — `command`, `timeout?` (seconds); stream stdout/stderr via `on_update`;
  spawn a process group and kill the whole tree on abort/timeout; tail-truncate, spill
  full output to a temp file when truncated.
- **grep** — backed by `ripgrep` if present (else a Python fallback). Params:
  `pattern`, `path?`, `glob?`, `ignoreCase?`, `literal?`, `context?`, `limit?`.
- **find** — backed by `fd` if present (else `pathlib`/`glob`). `pattern`, `path?`, `limit?`.
- **ls** — `path?`, `limit?`; alphabetical, `/` suffix for dirs, include dotfiles.
- **Shared** `tools/base.py`: truncation helpers (max lines / max bytes), path
  resolution relative to cwd, a consistent `ToolResult{content, details, is_error}`.

**Registry** (`tools/__init__.py`): name→factory map + bundle helpers
(`coding_tools(cwd)`, `read_only_tools(cwd)`), mirroring `tools/index.ts`. This is the
seam where second-brain users plug in custom tools.

**Tests:** each tool gets unit tests against a temp dir (golden behaviors:
truncation, edit uniqueness/failure, bash timeout/kill, grep/find fallbacks).

---

## Phase 5 — Agent loop  *(port `packages/agent/src/agent-loop.ts` — the heart)*

- `run_turn` / `run_loop`: nested loop — outer drains follow-up/steering queues, inner
  runs while there are tool calls or pending messages.
- Each turn: build `Context{systemPrompt, messages=to_llm(history), tools}`; call
  `model.stream(...)`; consume events, mutating a `partial` assistant message and
  emitting `message_update` events for live rendering; collect `toolCall` blocks.
- **Tool execution orchestration** (port `executeToolCalls`): validate args against
  the tool's JSON Schema; run **parallel by default**, **sequential** if any called
  tool is `execution_mode="sequential"` or globally configured; per-call `on_update`
  emits `tool_execution_update`; catch errors into error results; push `toolResult`
  messages back into history; honor a `terminate` flag.
- Hooks (keep, they enable the optional phases cleanly): `before_tool_call` (can
  **block** with a reason → permissions phase), `after_tool_call` (rewrite result),
  `transform_context` (→ compaction phase), `prepare_next_turn`, `should_stop_after_turn`.
- Cancellation: a cooperative `asyncio` cancel/abort that propagates to the model
  stream (`abort` to the shim) and to running tools.

**Tests:** drive the loop with a **fake model** (scripted event sequences) so the
loop is testable without network — assert turn structure, parallel vs sequential
execution, error handling, terminate, and abort. This fake is the single most
valuable test fixture in the project.

---

## Phase 6 — System prompt  *(port `system-prompt.ts`)*

- `build_system_prompt(tools, cwd, *, append=None, project_context=None, custom=None)`:
  base persona + an **Available tools** list built from each tool's `prompt_snippet`
  + a deduped **Guidelines** list from `prompt_guidelines` + always-on bullets +
  current date + cwd. Optional `<project_context>` from an `AGENTS.md`/`CLAUDE.md`
  file if present. Keep it programmatic (not one big string) so adding a tool updates
  the prompt automatically.

---

## Phase 7 — CLI / REPL / rendering  *(port the interactive mode, minimally)*

- `cli.py`: parse args (model, provider, cwd, one-shot `-p/--print`, `--no-session`).
- `app.py`: a REPL that reads a line, runs the loop to completion, supports Ctrl-C to
  abort the current turn; plus a non-interactive one-shot mode for scripting/tests.
- `render.py`: subscribe to loop events and render streaming assistant text/thinking,
  tool start/result, and a final usage line. Start simple with `rich`; a fuller TUI
  (`prompt_toolkit`/`textual`) is an optional upgrade.

**Deliverable after Phase 7: a working, testable coding agent** — read/edit/run code
in a directory, streamed to the terminal, model served by pi-ai.

---

## Testing strategy (cross-cutting)

1. **Unit** — tools (temp dirs), system-prompt assembly, schema validation, message
   conversion.
2. **Loop** — against the fake model fixture (no network): turn structure, tool
   orchestration, abort, terminate, hooks.
3. **Integration** — a handful of real end-to-end runs against a cheap model
   (Haiku), gated on an API key, in a scratch git repo: "read this file", "edit this
   function", "run the tests". Keep these few and deterministic.
4. **pi-py shim** — protocol tests for `PiModelClient` (Phase 0.4).
5. **CI** — run unit+loop tests always; integration tests only when a key is present.

---

## Optional / nice-to-have phases

These make it a fuller Pi clone but aren't needed for a functional example. Several
are worth implementing *differently/more simply* than Pi for teaching value — noted
inline.

- **A. Session persistence.** Pi uses a **tree** of entries (id/parentId, leaf-walk
  reconstruction) in JSONL under `~/.pi/agent/sessions/`. *Recommendation:* ship a
  **linear JSONL append log** first (trivial to read/resume) and offer the tree
  (fork/clone/branch) as an advanced variant. Port target: `packages/agent/src/harness/session/`.

- **B. Compaction.** Auto-summarize when `contextTokens > contextWindow - reserve`.
  Port `packages/agent/src/harness/compaction/`. *Recommendation:* implement as a
  `transform_context` hook so it's optional and swappable; a simple "summarize oldest
  N turns, keep recent K tokens" is enough to demonstrate. Branch summarization is
  advanced.

- **C. Permissions / approval.** Pi delegates this to extensions via the
  `before_tool_call` hook; there's no built-in sandbox. *Recommendation:* ship a
  built-in interactive approval gate for `bash`/`write`/`edit` (confirm before
  running), configurable allow/deny — this is an important safety layer and a great
  teaching example of the hook. Reference example extensions: `permission-gate.ts`,
  `confirm-destructive.ts`, `protected-paths.ts`.

- **D. Slash commands.** `/model`, `/compact`, `/new`, `/resume`, `/quit`, `/help`.
  Port subset of `slash-commands.ts`. Easy, high UX value.

- **E. Second-brain / memory tools.** The repurposing seam: add `note`, `recall`,
  `search_memory`, `remember` tools over a local store (sqlite/markdown). Demonstrates
  swapping the coding toolset for an assistant toolset via the same registry.

- **F. Sub-agents / task delegation.** Pi ships this only as an example extension
  (separate `pi` process per agent, markdown+frontmatter definitions). Advanced;
  build on the loop + a `Task` tool that spawns a child loop with a restricted toolset.

- **G. Images / vision.** read-tool image attachments + passing `ImageContent` to the
  model. pi-ai already supports it; just wire it through.

- **H. Auto-retry** on transient model errors (pi-ai surfaces errors as terminal
  events; wrap the turn in a retry policy). Pi has `retry.enabled/maxRetries`.

- **I. MCP tool servers.** Expose external MCP tools through the same `Tool` protocol.

- **J. Richer TUI** (textual/prompt_toolkit), HTML export, themes — pure polish.

---

## Suggested order

1. **Phase 0** (pi-py `PiModelClient` + shim) — unblocks everything.
2. Phases 1–3 (scaffold, types, model adapter).
3. Phase 4 (tools) + Phase 5 (loop) in tandem, against the fake-model fixture.
4. Phase 6 (prompt) + Phase 7 (CLI/REPL) → **functional agent**.
5. Then optional phases by value: **C (permissions) → D (slash) → A (sessions) →
   B (compaction) → E (memory) → others**.
</content>
</invoke>
