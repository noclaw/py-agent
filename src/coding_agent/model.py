"""Model adapter (Phase 3).

A thin wrapper over :class:`pi_py_sdk.model.PiModelClient` that the loop calls once per
assistant turn: build a context (system prompt + messages + tools), stream events, and
expose model/provider selection. Also a minimal model registry (port target:
``packages/coding-agent/src/core/model-registry.ts``) so custom/local models (Ollama, LM
Studio) can be declared as full pi-ai ``Model`` objects via an optional ``models.json``.

Credential resolution is handled entirely by pi-ai/the shim (caller key > env var >
``~/.pi/agent/auth.json`` OAuth) — nothing to implement here beyond passing an optional
key through.
"""

from __future__ import annotations
