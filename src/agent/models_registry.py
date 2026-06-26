"""Custom/local model registry — a small ``models.json`` for non-built-in models.

The built-in catalog covers a large set of models (Anthropic, OpenAI, …) which the CLI
lists and selects by id. This module adds the other half: models not in that catalog — a
local Ollama / LM Studio / vLLM server, or any OpenAI-compatible endpoint — declared in a
``models.json`` so they're selectable from the CLI just like built-in ones.

Discovery mirrors the rest of ``.pya/`` (project overrides user by ``provider/id``):

  - ``~/.pya/models.json``         (user)
  - ``<cwd>/.pya/models.json``     (project)

File shape: provider blocks carry the connection fields, each with a list of models::

    {
      "providers": {
        "local": {
          "baseUrl": "http://127.0.0.1:8008/v1",
          "api": "openai-completions",
          "apiKey": "...",
          "models": [
            {"id": "qwen3", "name": "Qwen3", "contextWindow": 32768, "maxTokens": 32768}
          ]
        }
      }
    }

A :class:`ModelInfo` for a custom model carries a flattened **spec** dict (provider fields
merged into the model) ready to hand to the provider's stream as a full ``model=`` object —
the seam that lets a local endpoint be streamed without a catalog entry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["ModelInfo", "ModelRegistry", "load_model_registry", "merge_catalog"]

#: Provider-level keys merged into each model's spec (the connection, not the model).
_PROVIDER_FIELDS = ("baseUrl", "api", "apiKey", "authHeader", "headers")

#: Defaults filled in for fields the model spec requires, so a minimal models.json
#: entry (just id + connection) works without crashing the provider's stream code.
_MODEL_DEFAULTS = {
    "reasoning": False,
    "input": ["text"],
    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    "contextWindow": 8192,
    "maxTokens": 4096,
}


@dataclass(frozen=True)
class ModelInfo:
    """One selectable model. ``spec`` is the full model spec for custom models, or
    ``None`` for built-ins (which are selected by ``provider``/``id`` against the catalog)."""

    provider: str
    id: str
    spec: dict[str, Any] | None = None
    source: str = "builtin"  # "builtin" | "user" | "project"

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.id}"

    @property
    def is_custom(self) -> bool:
        return self.spec is not None


@dataclass
class ModelRegistry:
    """The custom models declared in ``models.json`` files (built-ins are not stored here)."""

    custom: list[ModelInfo] = field(default_factory=list)

    def by_label(self) -> dict[str, ModelInfo]:
        return {m.label: m for m in self.custom}

    def resolve(self, provider: str | None, model_id: str) -> ModelInfo | None:
        """Return the custom :class:`ModelInfo` for ``provider/model_id`` (or a bare id),
        or ``None`` if it isn't a custom model (caller should treat it as a built-in id)."""
        for m in self.custom:
            if m.id == model_id and (provider is None or m.provider == provider):
                return m
        return None


def _model_spec(provider: str, block: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """Flatten a provider block + one model entry into a model spec."""
    spec: dict[str, Any] = {k: v for k, v in model.items()}
    spec["provider"] = provider
    spec.setdefault("name", model.get("id"))
    for key in _PROVIDER_FIELDS:
        if key in block and key not in spec:
            spec[key] = block[key]
    for key, default in _MODEL_DEFAULTS.items():
        spec.setdefault(key, default)
    return spec


def _parse(path: Path, source: str) -> list[ModelInfo]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:  # malformed JSON shouldn't crash the CLI
        raise ModelRegistryError(f"{path}: {exc}") from exc

    out: list[ModelInfo] = []
    for provider, block in (data.get("providers") or {}).items():
        for model in block.get("models") or []:
            mid = model.get("id")
            if not mid:
                continue
            out.append(
                ModelInfo(provider=provider, id=mid, spec=_model_spec(provider, block, model), source=source)
            )
    return out


class ModelRegistryError(Exception):
    """A ``models.json`` could not be read/parsed."""


#: User-level custom-models file (tests override this to isolate the real one).
USER_MODELS_PATH = Path.home() / ".pya" / "models.json"


def load_model_registry(cwd: str | Path = ".") -> ModelRegistry:
    """Load custom models from ``~/.pya/models.json`` then ``<cwd>/.pya/models.json``.

    Project entries override user entries with the same ``provider/id``.
    """
    sources = [
        (USER_MODELS_PATH, "user"),
        (Path(cwd) / ".pya" / "models.json", "project"),
    ]
    merged: dict[str, ModelInfo] = {}
    for path, source in sources:
        for info in _parse(path, source):
            merged[info.label] = info  # later (project) wins
    return ModelRegistry(custom=list(merged.values()))


def merge_catalog(builtin: list[dict[str, Any]], registry: ModelRegistry) -> list[ModelInfo]:
    """Combine the built-in catalog rows with custom models.

    Returns a sorted list of :class:`ModelInfo`; a custom model shadows a built-in with the
    same ``provider/id``.
    """
    infos: dict[str, ModelInfo] = {}
    for m in builtin:
        provider, mid = m.get("provider", ""), m.get("id", "")
        if provider and mid:
            infos[f"{provider}/{mid}"] = ModelInfo(provider=provider, id=mid)
    for m in registry.custom:
        infos[m.label] = m  # custom shadows built-in
    return sorted(infos.values(), key=lambda i: (i.provider, i.id))
