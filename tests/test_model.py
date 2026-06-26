"""The Model adapter: built-in ids vs full custom specs are forwarded correctly."""

from __future__ import annotations

import pytest

from agent.model import Model


class _RecordingClient:
    """Captures the kwargs passed to ``stream`` (and yields nothing)."""

    def __init__(self):
        self.last = None

    async def stream(self, **kwargs):
        self.last = kwargs
        return
        yield  # make it an async generator

    async def list_models(self, provider=None):
        return [{"provider": "anthropic", "id": "claude-sonnet-4-6"}]


async def _drain(model):
    async for _ in model.stream(messages=[]):
        pass


@pytest.mark.asyncio
async def test_builtin_streams_by_id():
    client = _RecordingClient()
    model = Model(client, provider="anthropic", model="claude-sonnet-4-6")
    await _drain(model)
    assert client.last["model"] == "claude-sonnet-4-6"  # a plain id string
    assert client.last["provider"] == "anthropic"


@pytest.mark.asyncio
async def test_custom_streams_full_spec():
    client = _RecordingClient()
    spec = {"id": "qwen3", "provider": "local", "api": "openai-completions", "baseUrl": "x"}
    model = Model(client, provider="local", model="qwen3", spec=spec)
    assert model.name == "local/qwen3"
    await _drain(model)
    assert client.last["model"] == spec  # the whole object, not just the id


@pytest.mark.asyncio
async def test_set_model_swaps_spec():
    client = _RecordingClient()
    model = Model(client, provider="anthropic", model="claude-sonnet-4-6")
    spec = {"id": "qwen3", "provider": "local"}
    model.set_model("qwen3", "local", spec=spec)
    await _drain(model)
    assert client.last["model"] == spec
    # Switching back to a built-in clears the spec.
    model.set_model("claude-opus-4-8")
    await _drain(model)
    assert client.last["model"] == "claude-opus-4-8"
