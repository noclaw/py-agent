# Models & providers

The model layer is delegated to Pi's `pi-ai` through the `pi-py` SDK — py-agent never talks
to a provider's HTTP API directly. This is what lets one small codebase support 30+
providers, OAuth, multiple transports, and local models. See
[architecture](architecture.md) for the shim.

## Choosing a model

```bash
uv run pya --provider anthropic --model claude-sonnet-4-6
uv run pya models                       # list everything pi-ai knows about
uv run pya models --provider anthropic  # filter to one provider
```

In the REPL, `/model claude-opus-4-8` (or `/model openai/gpt-...`) switches at runtime.
Defaults are in `agent/config.py` (`DEFAULT_PROVIDER`, `DEFAULT_MODEL`).

## Credentials

`pi-ai`/the shim resolve credentials in this order — there's nothing to implement in
Python beyond optionally passing a key:

1. an explicit key (rarely needed),
2. the provider's environment variable (e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `GEMINI_API_KEY`, …),
3. an existing Pi **OAuth login** in `~/.pi/agent/auth.json` (e.g. Claude Pro/Max via
   `pi` → `/login`). The shim reads and refreshes the token automatically.

So if you already use `pi`, py-agent works with no extra setup.

## Reasoning / thinking

`--reasoning {minimal,low,medium,high,xhigh}` sets the thinking level for models that
support it. Thinking is streamed and rendered dimmed.

## Local & custom models

`pi-ai` reaches local runtimes (Ollama, LM Studio, vLLM, …) and any OpenAI-compatible
endpoint by treating them as a `Model` with a `baseUrl` and an API flavor (usually
`openai-completions`) rather than a catalog entry.

**What `pya` selects today.** The `pya` CLI (and `pya models`) only sees `pi-ai`'s
*built-in* catalog — `--provider`/`--model` look an id up there. A custom provider you've
added to your `pi` install's `~/.pi/agent/models.json` is **not** enumerated by `pya
models` and isn't selectable by id from the CLI yet. Surfacing a model registry in py-agent
(reading a `models.json` so `--model` can name a local model) is a planned enhancement —
see `PLAN.md` ("models & providers").

**What works now: a full model spec, programmatically.** The underlying
`PiModelClient.stream` accepts a complete model object instead of a provider/model id, so
you can point it at a local endpoint directly:

```python
import asyncio
from pi_py_sdk import PiModelClient

LOCAL = {
    "id": "qwen3", "name": "qwen3", "provider": "local",
    "api": "openai-completions",
    "baseUrl": "http://127.0.0.1:8008/v1",
    "apiKey": "...",               # whatever your server expects
    "contextWindow": 32768, "maxTokens": 32768,
    "reasoning": False, "input": ["text"],
}

async def main():
    async with PiModelClient() as client:
        async for ev in client.stream(
            model=LOCAL,            # full spec, not an id
            messages=[{"role": "user", "content": "hello", "timestamp": 0}],
        ):
            if ev.type == "text_delta":
                print(ev.delta, end="", flush=True)

asyncio.run(main())
```

py-agent's own `agent/model.py` wrapper currently types `model` as a string, so to drive
the *agent loop* against a local model today you'd extend `Model`/`open_model` to pass the
spec through — the seam is already there (`stream` forwards `model` to the client). That
small registry is the planned work above. A local server's key goes in the spec's
`apiKey`; built-in providers still resolve via env var or `~/.pi/agent` OAuth as above.

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
