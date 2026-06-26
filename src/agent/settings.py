"""User settings — ``~/.pya/settings.toml``.

A hand-edited per-user config (it holds API keys, so **chmod 600** it). It lets you:

- **avoid exporting keys** — put `api_key` per provider here instead,
- **scope the catalog** — only providers listed here are offered by `pya models` / the
  `/model` picker (plus any local models in `.pya/models.json`),
- **curate models** — an optional `models` allowlist per provider, and a `default` model.

Read-only here; `pya auth` / `pya config` management commands can come later. Schema::

    default = "anthropic/claude-opus-4-8"     # optional

    [providers.anthropic]
    api_key = "sk-ant-api03-..."              # optional (else the provider's env var)
    models  = ["claude-opus-4-8", "claude-sonnet-4-6"]   # optional allowlist

    [providers.openai]
    api_key = "sk-..."
    models  = ["gpt-5.1", "gpt-5-codex"]

Credential precedence is ``.pya/models.json`` spec key → provider env var → this file, so a
key here means "no export needed", while an env var still overrides it (handy in CI).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Settings", "ProviderConfig", "load", "SETTINGS_PATH"]

SETTINGS_PATH = Path.home() / ".pya" / "settings.toml"


def _default_path() -> Path:
    env = os.environ.get("PYA_SETTINGS_FILE")
    return Path(env) if env else SETTINGS_PATH


@dataclass(frozen=True)
class ProviderConfig:
    """One ``[providers.<name>]`` block."""

    api_key: str | None = None
    models: tuple[str, ...] = ()  # allowlist; empty = the curated built-ins for this provider


@dataclass(frozen=True)
class Settings:
    default_provider: str | None = None
    default_model: str | None = None
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        """True if the file declared any providers (so it should govern the catalog)."""
        return bool(self.providers)

    def api_key(self, provider: str) -> str | None:
        cfg = self.providers.get(provider)
        return cfg.api_key if cfg else None

    def model_list(self, extra_providers: tuple[str, ...] = ()) -> list[dict[str, str]]:
        """The ``{provider, id}`` rows to offer for each active provider: its allowlist, or
        the curated built-ins for that provider when it has none. ``extra_providers`` (e.g.
        providers that only have a stored key) are included with their built-in subset."""
        from .providers.catalog import BUILTIN_MODELS

        names = list(self.providers) + [p for p in extra_providers if p not in self.providers]
        rows: list[dict[str, str]] = []
        for name in names:
            cfg = self.providers.get(name)
            if cfg and cfg.models:
                rows.extend({"provider": name, "id": mid} for mid in cfg.models)
            else:
                rows.extend(bm for bm in BUILTIN_MODELS if bm["provider"] == name)
        return rows


def load(path: Path | None = None) -> Settings:
    """Load and parse the settings file; an absent/invalid file yields empty defaults."""
    path = path or _default_path()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return Settings()

    default = data.get("default")
    dp = dm = None
    if isinstance(default, str) and "/" in default:
        dp, dm = default.split("/", 1)

    providers: dict[str, ProviderConfig] = {}
    for name, block in (data.get("providers") or {}).items():
        if isinstance(block, dict):
            models = block.get("models") or []
            providers[name] = ProviderConfig(
                api_key=block.get("api_key"),
                models=tuple(str(m) for m in models),
            )
    return Settings(default_provider=dp, default_model=dm, providers=providers)


def catalog_models() -> list[dict[str, str]]:
    """The built-in catalog rows to offer, scoped to the providers in use — those declared in
    settings and those that have a stored key (``pya auth set``). Falls back to the full
    curated catalog when nothing is configured."""
    from .providers import oauth
    from .providers.catalog import builtin_models

    settings = load()
    keyed = tuple(p for p, kind in oauth.list_credentials().items() if kind == "api_key")
    if settings.configured or keyed:
        return settings.model_list(extra_providers=keyed)
    return builtin_models()


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save(settings: Settings, path: Path | None = None) -> None:
    """Write ``settings`` back to the TOML file (used by ``pya config``).

    Serializes only the schema fields — any comments in a hand-edited file are not preserved.
    """
    path = path or _default_path()
    lines: list[str] = []
    has_secret = False
    if settings.default_provider and settings.default_model:
        lines.append(f'default = "{settings.default_provider}/{settings.default_model}"')
        lines.append("")
    for name in sorted(settings.providers):
        cfg = settings.providers[name]
        lines.append(f"[providers.{name}]")
        if cfg.api_key:
            lines.append(f"api_key = {_toml_str(cfg.api_key)}")
            has_secret = True
        if cfg.models:
            lines.append("models = [" + ", ".join(_toml_str(m) for m in cfg.models) + "]")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    if has_secret:
        try:
            import os

            os.chmod(path, 0o600)
        except OSError:
            pass
