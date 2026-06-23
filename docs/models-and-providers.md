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

`pi-ai` reaches local runtimes (Ollama, LM Studio, …) and custom endpoints by treating
them as a `Model` with a `baseUrl` and an API flavor (usually OpenAI-completions). Pi
configures these in a `models.json`; surfacing the same in py-agent (a small model
registry) is a planned enhancement — see `PLAN.md` ("models & providers"). Until then, the
simplest path for a local model is to configure it in your `pi` install (which the shim
reads) and select it with `--provider/--model`.

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
