# Models & providers

The model layer is native Python (`agent/providers/`) talking directly to provider HTTP APIs
over `httpx` — no Node, no SDK. Two backends ship: **`openai-completions`** (OpenAI and any
OpenAI-compatible server — Ollama, LM Studio, vLLM, Groq, Together, OpenRouter, …) and
**`anthropic-messages`** (Claude). To support another transport, implement the `Provider`
protocol. See [architecture](architecture.md) and [`PROVIDERS.md`](../PROVIDERS.md).

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

Defaults are in `agent/config.py` (`DEFAULT_PROVIDER`, `DEFAULT_MODEL`).

## Credentials

Resolution order (per provider):

1. an explicit key in a custom model's `.pya/models.json` spec (`apiKey`),
2. the provider's environment variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `GROQ_API_KEY`, …),
3. for Anthropic only: a Claude **Pro/Max OAuth login**. Run **`pya login`** — a native
   PKCE browser flow (a local callback on `127.0.0.1:53692`, or `pya login --manual` to
   paste the redirect URL) that stores the token in `~/.pya/auth.json`; `pya logout` clears
   it. `agent/providers/oauth.py` reads and auto-refreshes it, sending the bearer token with
   the `anthropic-beta: oauth-2025-04-20` header. An existing `pi` login
   (`~/.pi/agent/auth.json`) is also read as a fallback.

So `pya login` once and Anthropic works with no env var — no Node, no `pi`.

## Reasoning / thinking

`--reasoning {minimal,low,medium,high,xhigh}` sets the thinking level for models that
support it. Thinking is streamed and rendered dimmed.

## Local & custom models

`pi-ai` reaches local runtimes (Ollama, LM Studio, vLLM, …) and any OpenAI-compatible
endpoint by treating them as a model with a `baseUrl` and an API flavor (usually
`openai-completions`) rather than a built-in catalog entry. py-agent makes these selectable
from the CLI via a small **model registry**: a `models.json` under `.pya/`.

### Declare a model

Create `~/.pya/models.json` (applies everywhere) or `<cwd>/.pya/models.json` (just this
project; project entries override user ones by `provider/id`). The shape matches pi's own
`models.json` — a provider block with the connection fields and a list of models:

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
built-in providers, credentials still resolve via env var or `~/.pi/agent` OAuth as above.

Under the hood the registry flattens each entry into a full pi-ai model object and streams
it as a `model=` spec (the `PiModelClient.stream` seam accepts an id *or* a full object).
See `agent/models_registry.py`.

## Under the hood

`agent/model.py` wraps `pi_py_sdk.PiModelClient`:

```python
from agent.model import open_model

async with open_model(provider="anthropic", model="claude-sonnet-4-6", reasoning="low") as m:
    async for event in m.stream(system_prompt=sp, messages=wire_messages, tools=wire_tools):
        ...   # StreamEvent: text_delta / thinking_delta / toolcall_end / done / error
```

`open_model` starts the Node shim subprocess and yields a `Model`; extra keyword args
(e.g. `maxTokens`, `temperature`) pass through to pi-ai's stream options verbatim.
