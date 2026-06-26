# Models & providers

The model layer is native Python (`agent/providers/`) talking directly to provider HTTP APIs
over `httpx` — no Node, no SDK. Two backends ship: **`openai-completions`** (OpenAI and any
OpenAI-compatible server — Ollama, LM Studio, vLLM, Groq, Together, OpenRouter, …) and
**`anthropic-messages`** (Claude). To support another transport, implement the `Provider`
protocol. See [architecture](architecture.md).

## Choosing a model

```bash
uv run pya --provider anthropic --model claude-opus-4-8
uv run pya models                       # curated built-ins + your custom models
uv run pya models --provider anthropic  # filter to one provider
```

In the REPL, switch at runtime two ways:

- `/model claude-opus-4-8` (or `/model openai/gpt-5.1`) — switch by id.
- `/model` with **no argument** opens an interactive **fuzzy picker**: type to filter,
  `↑`/`↓` to move, `Enter` to select, `Esc` to cancel. It lists every available model
  (built-in + your custom ones, below). The current model is marked.

Defaults are in `agent/config.py` (`DEFAULT_PROVIDER`, `DEFAULT_MODEL`), overridable by
`default` in `settings.toml` (below).

## Settings (`~/.pya/settings.toml`)

A hand-edited per-user config so you don't have to `export` keys, can scope which providers
the CLI offers, and can curate the model list. **`chmod 600`** it — it holds API keys — and
keep it out of any repo.

```toml
default = "anthropic/claude-opus-4-8"        # optional default model

# Optional runtime defaults (each also a CLI flag; the flag wins, then this, then the
# built-in default). reasoning, permission_mode, max_retries, context_window, compact, subagent:
reasoning       = "low"                      # minimal|low|medium|high|xhigh
permission_mode = "acceptEdits"              # default|acceptEdits|plan|bypass
max_retries     = 2
compact         = true
# context_window = 200000                    # omit to infer from the model's metadata

[providers.anthropic]
api_key = "sk-ant-api03-..."                 # optional (else the provider's env var / pya auth)
models  = ["claude-opus-4-8", "claude-sonnet-4-6"]   # optional allowlist

[providers.openai]
api_key = "sk-..."
models  = ["gpt-5.1", "gpt-5-codex"]
```

- **No `export`** — `api_key` is read at runtime.
- **Only the providers in use** — `pya models` and the `/model` picker show only the
  providers you've configured here *or* given a key via `pya auth set`, plus any local models
  from `.pya/models.json`. (With nothing configured, the full curated catalog shows.)
- **Curated models** — `models = [...]` is exactly what you can pick; omit it to fall back to
  the curated built-ins for that provider.
- **Runtime defaults** — the scalar keys set defaults for the matching CLI flags. A CLI flag
  always overrides; `context_window` is otherwise inferred per model from the catalog/registry
  metadata (the `--context-window` flag still overrides).

The `api_key` is keyed by provider name, so it also supplies the key for a local provider
defined in `.pya/models.json` (keep the key here, the endpoint there). Set
`PYA_SETTINGS_FILE` to point at a different file.

You can edit the file by hand, or use **`pya config`** (note: `pya config` rewrites the file,
so hand-added comments aren't preserved):

```bash
pya config show
pya config set-default anthropic/claude-opus-4-8
pya config set reasoning low                    # any scalar key; `pya config unset <key>` clears it
pya config set permission_mode acceptEdits
pya config models openai gpt-5.1 gpt-5-codex    # set a provider's allowlist (also enables it)
pya config models groq                           # enable a provider with the curated built-ins
pya config remove-provider openai
```

Keys are best stored with `pya auth set` (see [Credentials](#credentials)) rather than in
this file, so `pya config` never has to touch secrets.

## Credentials

Two ways to store a key without exporting it: the **`pya auth`** command (writes a managed
JSON store), or **`settings.toml`** (hand-edited). Resolution order (per provider):

1. an explicit key in a custom model's `.pya/models.json` spec (`apiKey`),
2. the provider's environment variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …),
3. a key stored by `pya auth set` (`~/.pya/auth.json`, `chmod 600`),
4. the provider's `api_key` in `~/.pya/settings.toml`.

So either store means no `export` is needed; an env var still overrides them (handy in CI).

```bash
pya auth set openai          # prompts (hidden) and stores the key in ~/.pya/auth.json
pya auth set openai --key sk-...   # non-interactive
pya auth list                # providers with a stored credential
pya auth remove openai
```

Anthropic uses an **API key** (`ANTHROPIC_API_KEY` or `settings.toml`). (Claude Pro/Max OAuth isn't used:
Anthropic no longer applies subscription credits to standard API usage, so an OAuth
subscription token only hits subscription rate limits here.) A provider-neutral OAuth
toolkit is kept in `agent/providers/oauth.py` for a future OpenAI-compatible OAuth provider,
but it isn't wired to anything today.

## Reasoning / thinking

`--reasoning {minimal,low,medium,high,xhigh}` sets the thinking level for models that
support it. Thinking is streamed and rendered dimmed.

## Local & custom models

py-agent reaches local runtimes (Ollama, LM Studio, vLLM, …) and any OpenAI-compatible
endpoint by treating them as a model with a `baseUrl` and an API flavor (usually
`openai-completions`) rather than a built-in catalog entry. py-agent makes these selectable
from the CLI via a small **model registry**: a `models.json` under `.pya/`.

### Declare a model

Create `~/.pya/models.json` (applies everywhere) or `<cwd>/.pya/models.json` (just this
project; project entries override user ones by `provider/id`). The shape is a provider block
with the connection fields and a list of models:

```json
{
  "providers": {
    "local": {
      "baseUrl": "http://127.0.0.1:8008/v1",
      "api": "openai-completions",
      "apiKey": "your-key-or-anything-the-server-wants",
      "models": [
        { "id": "qwen3", "name": "Qwen3", "contextWindow": 32768, "maxTokens": 4096 }
      ]
    }
  }
}
```

Only `id` and the provider's `baseUrl`/`api` are really required — `contextWindow`,
`maxTokens`, `reasoning`, `input`, and `cost` are filled with sensible defaults if omitted.

### Use it

Custom models then behave like any other:

```bash
pya models                                  # lists built-ins + your custom ones (tagged [custom])
pya --provider local --model qwen3 -p "hi"  # select by id from the CLI
```

In the REPL, `/model` (no args) shows them in the fuzzy picker alongside built-ins, or
`/model local/qwen3` switches directly. The model's `apiKey` is sent as the credential; for
built-in providers, credentials resolve via the provider's env var as above.

Under the hood the registry flattens each entry into a full model spec; the provider streams
it directly. See `agent/models_registry.py`.

## Under the hood

`agent/model.py` routes to a native provider:

```python
from agent.model import open_model

async with open_model(provider="anthropic", model="claude-sonnet-4-6", reasoning="low") as m:
    async for event in m.stream(system_prompt=sp, messages=wire_messages, tools=wire_tools):
        ...   # StreamEvent: text_delta / thinking_delta / toolcall_end / done / error
```

`open_model` yields a `Model`; extra keyword args (e.g. `maxTokens`, `temperature`) pass
through to the provider's request verbatim.
