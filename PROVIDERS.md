# PROVIDERS.md — native Python model layer (eliminate `pi_py_sdk`)

Status: **Phase 1 shipped; Phases 2–3 pending.** This document describes replacing the
delegated model layer (pi-ai via the `pi-py` SDK + Node shim) with a small, native-Python
provider layer talking directly to provider HTTP APIs.

**Phase 1 (done):** native OpenAI-compatible backend over httpx (`agent/providers/`),
routing in `agent/model.py` by the model's `api`. OpenAI-compatible + custom/local models
(`.pya/models.json`) stream natively — verified against OpenAI and a live local server. The
pi backend is started **lazily** (only for Anthropic), so OpenAI-only runs spawn no Node.
Decisions taken: Anthropic OAuth → Phase 2; clean break (remove `pi_py_sdk` when Phase 2
lands); tiny static catalog (`providers/catalog.py`); forward-only sessions.

Known Phase-1 limits (resolved by Phase 2): Anthropic still routes through `pi_py_sdk` (Node),
and `pya models` / the REPL picker still list via pi (so the REPL still starts Node). Native
types currently reuse `pi_py_sdk`'s `StreamEvent`/`AssistantMessage`; Phase 2 introduces
`agent/wire.py` and removes the dependency.

## Goal & scope

Today py-agent delegates the raw model call to pi-ai (TypeScript) through `pi_py_sdk`'s
`PiModelClient`, which spawns a Node shim. The recent pi-ai 0.80 refactor broke that shim
(the `./compat` entrypoint move), and threading local-model specs through a subprocess is
awkward. This plan makes the model layer native Python.

**In scope**
- Remove `pi_py_sdk` **entirely** — no Node, no shim, no subprocess. Drop the dependency.
- **Phase 1: OpenAI-compatible** (`/v1/chat/completions`). Covers OpenAI *and* essentially
  every local runtime (Ollama, LM Studio, vLLM, llama.cpp) and OpenAI-compatible clouds
  (Together, Groq, OpenRouter, …) — directly serving "better control of local models."
- **Phase 2: Anthropic Messages** (`/v1/messages`) — first-class Claude with thinking,
  prompt caching, tool use.
- **Phase 3 (optional): OAuth** for Claude (Pro/Max) and/or OpenAI Codex.

**Explicitly out of scope** (per decision)
- Unique transports: **Amazon Bedrock (SigV4), Google Vertex/Gemini (GCP auth), Azure**.
  A user needing these adds custom code behind the provider interface (see "Escape hatch").
- pi-ai's 30+ provider breadth and its large auto-generated model catalog.
- The OpenAI *Responses* API and Codex-responses transport (chat-completions covers the
  models we care about, including gpt-5 / o-series, via `/v1/chat/completions`).

## Why this is low-risk: the seam already exists

The agent loop depends on a tiny contract — `ModelLike` (`agent/model.py`):

```python
class ModelLike(Protocol):
    def stream(self, *, system_prompt, messages, tools) -> AsyncIterator[StreamEvent]: ...
```

Everything else — the loop, tools, permissions, hooks, sessions, compaction, retry,
sub-agents, the model registry, and the `/model` picker — is backend-agnostic. A native
provider layer is a **drop-in replacement for the transport inside `Model`**, not a rewrite
of the agent.

**Key design choice that minimizes churn:** define native types (`StreamEvent`,
`AssistantMessage`, `ToolCall`) that mirror the *shapes* `pi_py_sdk` exposes today. Then
`types.py`, `render.py`, `loop.py`, `sessions.py`, and the test fakes change only their
**import source**, not their logic.

## What `pi_py_sdk` provides today → native replacement

Inventory from the current tree (every touchpoint):

| Used today (from `pi_py_sdk`) | Where | Native replacement |
|---|---|---|
| `StreamEvent` (`type`, `delta`, `contentIndex`, `toolCall`, `message`, `error`, `is_terminal`, `final_message`) | `model.py`, `types.py`, `render.py`, `loop.py`, fakes/tests | `agent/wire.py: StreamEvent` (same fields/properties) |
| `AssistantMessage` (pydantic, `role`/`content`/`stopReason`/`usage`/`errorMessage`, `extra="allow"`) | `types.py`, sessions, compaction, render, tests | `agent/wire.py: AssistantMessage` (pydantic, same shape) |
| `ToolCall` (`id`/`name`/`arguments`) | fakes | `agent/wire.py: ToolCall` |
| `PiError` | `app.py`, `cli.py` | `agent/providers/errors.py: ProviderError` |
| `PiModelClient.stream(...)` | `model.py` | `Provider.stream(...)` over httpx (per-API impl) |
| `PiModelClient.list_models(...)` / `PiModelClientSync` | `cli.py` (`pya models`), `model.py` | `Provider.list_models()` (HTTP `GET /models`) + registry + static catalog |
| Credential resolution (env var > `~/.pi/agent/auth.json` OAuth) | shim | `agent/providers/auth.py` (env var; OAuth in Phase 3) |
| Wire message format (pi-ai dicts via `to_llm_messages`) | `types.py` | Each provider builds its own request body from our canonical messages |

## Target architecture

```
src/agent/
  wire.py                  # NEW: native StreamEvent / AssistantMessage / ToolCall / content blocks
  model.py                 # Model/open_model: route to a Provider by the model's `api` (no PiModelClient)
  providers/
    __init__.py            # registry of api-id -> Provider; select_provider(model_spec)
    base.py                # Provider protocol: stream(...) + list_models(); shared option mapping
    http.py                # httpx client + SSE line reader (shared)
    errors.py              # ProviderError (replaces PiError)
    auth.py                # credential resolution: env keys now; OAuth (Phase 3)
    catalog.py             # small static map: known provider -> {baseUrl, api, env_var}; a few model metadata rows
    openai_compat.py       # Phase 1: /v1/chat/completions
    anthropic.py           # Phase 2: /v1/messages
```

`models_registry.py` (already shipped) stays almost unchanged: a custom model's spec already
carries `api` + `baseUrl` + `apiKey`, which is exactly what `select_provider` dispatches on.

## The canonical types (`agent/wire.py`)

These replace the pi-ai types and become the project's own contract. Match the existing
shapes so downstream code is untouched.

- **Content blocks** (list on an assistant message), as dicts today:
  - `{"type": "text", "text": ...}`
  - `{"type": "thinking", "text": ..., "signature": ...}` — **`signature`/opaque fields must
    round-trip** (Anthropic requires the thinking signature on the next turn; OpenAI may
    return encrypted reasoning). Preserve unknown keys.
  - `{"type": "toolCall", "id": ..., "name": ..., "arguments": {...}}`
- **`AssistantMessage`** (pydantic, `extra="allow"`): `role`, `content`, `stopReason`
  (`stop`|`length`|`toolUse`|`error`|`aborted`), `usage` (`{totalTokens, inputTokens,
  outputTokens, ...}`), `errorMessage`. `model_dump(exclude_none=True)` / `model_validate`
  keep working for sessions.
- **`StreamEvent`**: `type` ∈ {`text_delta`, `thinking_delta`, `toolcall_delta`,
  `toolcall_end`, `done`, `error`}; plus `delta`, `contentIndex`, `toolCall`, `message`,
  `error`; properties `is_terminal` (done/error) and `final_message`.

The loop only needs: stream the deltas, then a terminal event carrying the assembled
`final_message`. Each provider's job is to turn its SSE into this sequence.

## Phase 1 — OpenAI-compatible backend

**Endpoint:** `POST {baseUrl}/chat/completions` with `stream: true`, `stream_options:
{include_usage: true}`. `baseUrl` from the model spec/catalog (`https://api.openai.com/v1`
for OpenAI; arbitrary for local servers).

**Request building** (`messages` + `tools` → body):
- Convert our messages → OpenAI `messages`: user→`user`; tool result→`role: "tool"` with
  `tool_call_id`; assistant→`assistant` with `content` and `tool_calls` (id/function
  name/arguments). System prompt → a leading `system` message.
- Tools → `tools: [{type:"function", function:{name, description, parameters}}]` (we already
  have JSON Schema from `Tool.json_schema()`).
- Options: `reasoning_effort` from `--reasoning`; `max_tokens`, `temperature` passthrough.

**Streaming parse** (SSE `data:` lines, `[DONE]` sentinel):
- `choices[].delta.content` → `text_delta`.
- `choices[].delta.tool_calls[]` → accumulate by index (id, name, **argument string
  fragments**); emit `toolcall_end` when complete (assemble + `json.loads` arguments).
- `choices[].delta.reasoning` / reasoning fields (some servers) → `thinking_delta`.
- `finish_reason` → `stopReason` (`stop`→stop, `length`→length, `tool_calls`→toolUse).
- Final `usage` (`prompt_tokens`/`completion_tokens`/`total_tokens`) → normalized `usage`.
- Assemble the full `AssistantMessage`, emit terminal `done` (or `error`).

**`list_models()`:** `GET {baseUrl}/models` → `data[].id`. Works for OpenAI and most local
servers; on failure, fall back to the static catalog + registry (so the picker still works).

**Tests:** golden request body for a tool-calling turn; SSE fixtures (text-only, tool call
split across chunks, usage tail, mid-stream error) → assert the `StreamEvent` sequence and
final message. No network.

## Phase 2 — Anthropic Messages backend

**Endpoint:** `POST {baseUrl}/messages` (`https://api.anthropic.com/v1`), headers
`x-api-key`, `anthropic-version`, `stream: true`.

**Request building:**
- System prompt → top-level `system` (string or blocks).
- Messages → Anthropic `messages` with content blocks; tool result → `{type:"tool_result",
  tool_use_id, content}`; assistant tool call → `{type:"tool_use", id, name, input}`.
- **Thinking:** map `--reasoning` → `thinking: {type:"enabled", budget_tokens: N}`; preserve
  returned `thinking` blocks **with their `signature`** and send them back next turn.
- **Prompt caching (high value):** set `cache_control: {type:"ephemeral"}` breakpoints on
  the system prompt / tool definitions / last stable turn. (Can land as a 2.1 refinement.)
- Tools → `[{name, description, input_schema}]`.

**Streaming parse** (Anthropic event SSE: `message_start`, `content_block_start/delta/stop`,
`message_delta`, `message_stop`):
- `content_block_delta` text → `text_delta`; thinking → `thinking_delta` (+ capture
  `signature` on `content_block_stop`).
- `content_block_start`/`delta` for `tool_use` → accumulate `input_json` fragments →
  `toolcall_end`.
- `message_delta.stop_reason` (`end_turn`/`max_tokens`/`tool_use`) → `stopReason`.
- `usage` (`input_tokens`/`output_tokens`/`cache_*`) → normalized `usage`.

**`list_models()`:** `GET /v1/models` → `data[].id`.

**Tests:** as Phase 1 — golden bodies + Anthropic SSE fixtures (text, thinking+signature,
tool_use, usage), assert sequence + signature round-trip.

## Phase 3 (optional) — OAuth for Claude / Codex

Today the shim can authenticate from a Pi OAuth login at `~/.pi/agent/auth.json` (Claude
Pro/Max). Eliminating `pi_py_sdk` drops that unless ported.

- **Anthropic OAuth** (Pro/Max): PKCE flow + token refresh (pi-ai's `utils/oauth/anthropic.ts`
  is ~440 lines). We can keep reading the existing `~/.pi/agent/auth.json` token shape for
  drop-in compatibility, then send `Authorization: Bearer` + the OAuth beta header.
- **OpenAI Codex OAuth:** larger (~device-code/PKCE). Lower priority.
- **Default without Phase 3:** API keys via env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  or any provider's key / a local server's key from the registry spec). This is enough for
  Phases 1–2; OAuth is a convenience.

Decision needed: do enough users rely on Claude Pro/Max OAuth that Phase 3-Anthropic should
be promoted into Phase 2? (See open questions.)

## The genuinely hard parts (where the bugs live)

pi-ai's provider files are ~1,250 lines *each* because they absorb these. We accept fewer
quirks, but must still get the core right:

1. **Tool-call streaming assembly** — arguments arrive as string fragments across chunks
   (OpenAI by index; Anthropic as `input_json_delta`). Assemble, then parse JSON once.
2. **Opaque field round-tripping** — Anthropic thinking `signature`, tool-call ids, any
   encrypted reasoning. If not echoed back verbatim, multi-turn breaks. Preserve unknown
   keys end-to-end (sessions already store assistant messages verbatim).
3. **Usage normalization** — different field names per API → one `usage` dict (`render.py`
   reads `totalTokens`).
4. **Stop-reason mapping** — to the loop's vocabulary; `error`/`aborted` drive retry.
5. **Error & retry semantics** — map HTTP/stream errors to a terminal `error` event so the
   existing `RetryPolicy` keeps working (it keys off `stopReason == "error"`).
6. **Cancellation** — Ctrl-C cancels the turn task; the httpx stream must close cleanly in a
   `finally`.

## Migration & cleanup checklist

- [ ] Add `agent/wire.py` with native `StreamEvent`/`AssistantMessage`/`ToolCall`.
- [ ] Repoint imports: `types.py`, `render.py`, `loop.py`, `sessions.py`, `tests/fakes.py`,
      and tests — change `from pi_py_sdk import …` → `from .wire import …` (shapes identical).
- [ ] Rewrite `model.py`: `Model`/`open_model` route to a `Provider` by `api`; drop
      `PiModelClient`. Keep `Model.list_models`, `set_model(..., spec=)`, `name`.
- [ ] Add `providers/` (base, http, errors, auth, catalog, openai_compat) — **Phase 1**.
- [ ] Update `cli.py` `pya models` to use `Provider.list_models()` (sync via httpx.Client or
      `asyncio.run`); replace `PiError`/`PiModelClientSync`.
- [ ] Update `app.py`: replace `PiError` with `ProviderError`.
- [ ] Add `providers/anthropic.py` — **Phase 2**.
- [ ] `pyproject.toml`: remove `pi-py-sdk`; add `httpx`. **Drop the Node/`pi` requirement.**
- [ ] Docs: rewrite `CLAUDE.md` core principle (it currently says *don't* reimplement
      providers — this plan reverses that), `README` architecture, `docs/architecture.md`,
      `docs/models-and-providers.md`, `docs/getting-started.md`/`QUICKSTART.md` (no Node).
- [ ] `PLAN.md`: move "native provider layer" into Status when done.

## What we deliberately drop (and the escape hatch)

- Lost: Bedrock/Vertex/Gemini/Azure/Copilot transports, pi-ai's big priced catalog, 30+
  providers out of the box, and pi-ai's upstream maintenance + test suite.
- **Escape hatch:** the `Provider` protocol is the extension point. A user needing Bedrock
  writes a `Provider` subclass (SigV4 signing, etc.) and registers it under an `api` id;
  their model's spec in `.pya/models.json` selects it. We document the interface; we don't
  ship the exotic transports.

## Dependency & install impact (a net simplification)

- **Removed:** `pi-py-sdk`, **Node**, the global `pi`/`pi-ai` install, the subprocess shim.
- **Added:** `httpx` (async streaming HTTP). SSE parsed by hand over `aiter_lines()` — no SSE
  lib needed.
- Install becomes pure Python: `uv sync` / `uv tool install .`, set a provider key, done.
  This *strengthens* the "readable Python, minimal moving parts" thesis (ironically by
  inverting the old "only the LLM call leaves the process" principle — make that change
  consciously in `CLAUDE.md`).

## Effort & sequencing

- **Phase 1 (OpenAI-compatible):** the highest-leverage slice — unlocks local models + OpenAI.
  ~600–1,000 lines (wire types + http/SSE + openai_compat + auth-by-env + catalog) plus
  tests. This is the milestone that delivers most of the value.
- **Phase 2 (Anthropic):** ~500–800 lines + tests (thinking/signatures/caching add the
  fiddliness). After this, `pi_py_sdk` can be removed entirely.
- **Phase 3 (OAuth):** optional; Anthropic ~a few hundred lines, Codex more.

Suggested order: land Phase 1 behind the existing `ModelLike` seam (both backends can
coexist with the shim during transition if desired), validate against a local server + OpenAI,
then Phase 2, then delete `pi_py_sdk`. Tests use canned request/response fixtures — no
network, mirroring the project's fake-model discipline.

## Open questions / decisions

1. **Claude OAuth timing** — promote Anthropic OAuth into Phase 2, or ship API-key-only first
   and add OAuth in Phase 3? (Depends on whether Pro/Max login is a must-have day one.)
2. **Coexistence vs. clean break** — keep `pi_py_sdk` selectable as a fallback backend during
   the transition, or remove it the moment Phase 2 lands? (Plan assumes removal after Phase 2.)
3. **Model metadata** — ship a tiny static catalog (context window/pricing for the few known
   models) so compaction can infer `--context-window`, or keep the flag and rely on
   registry-provided `contextWindow`? (Ties into the planned `settings.toml`.)
4. **Session compatibility** — old sessions store pi-ai assistant dicts; native shape is
   nearly identical, but confirm `message_from_wire` reads both, or accept forward-only.
```
