"""Command-line entry point (``pya``).

Phase 1 wires a runnable skeleton: ``--version``, a ``models`` smoke command that proves
the whole stack (this package -> pi-py -> Node shim -> pi-ai) works end to end, and a
default command that launches the (still-stubbed) interactive app. The real arg surface
(model/provider/cwd/one-shot/no-session) fills in alongside the loop and app phases.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import __version__
from .config import DEFAULT_MODEL, DEFAULT_PROVIDER


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pya",
        description="A readable Python coding agent (model layer via pi-py/pi-ai).",
    )
    parser.add_argument("--version", action="version", version=f"pya {__version__}")
    parser.add_argument(
        "--model",
        default=None,
        help=f"Model id (default: ~/.pya/settings.toml `default`, else {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help=f"Provider id (default: from settings, else {DEFAULT_PROVIDER}).",
    )
    parser.add_argument(
        "--reasoning",
        default=None,
        choices=["minimal", "low", "medium", "high", "xhigh"],
        help="Thinking level (default: provider default).",
    )
    parser.add_argument(
        "--cwd",
        default=".",
        help="Working directory the agent operates in (default: current directory).",
    )
    parser.add_argument(
        "--permission-mode",
        default="default",
        choices=["default", "acceptEdits", "plan", "bypass"],
        help=(
            "How to gate mutating tools: default (ask), acceptEdits (auto-allow "
            "write/edit), plan (deny mutations), bypass (allow everything)."
        ),
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="Skip all permission prompts (alias for --permission-mode bypass).",
    )
    parser.add_argument(
        "-c",
        "--continue",
        dest="continue_session",
        action="store_true",
        help="Resume the most recent session for this directory.",
    )
    parser.add_argument(
        "--resume",
        metavar="SESSION_ID",
        default=None,
        help="Resume a specific session by id.",
    )
    parser.add_argument(
        "--no-session",
        action="store_true",
        help="Don't save this conversation to disk.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retries for transient model errors per turn (0 disables; default: 2).",
    )
    parser.add_argument(
        "--no-compact",
        action="store_true",
        help="Disable auto-compaction of old history as it nears the context window.",
    )
    parser.add_argument(
        "--context-window",
        type=int,
        default=200_000,
        help="Model context window in tokens, used to size compaction (default: 200000).",
    )
    parser.add_argument(
        "--no-subagent",
        action="store_true",
        help="Don't expose the `task` tool (sub-agent delegation).",
    )
    parser.add_argument(
        "-p",
        "--print",
        dest="prompt",
        default=None,
        metavar="PROMPT",
        help="Run a single prompt non-interactively and exit (otherwise start a REPL).",
    )

    sub = parser.add_subparsers(dest="command")

    p_models = sub.add_parser("models", help="List available models (built-ins + custom).")
    p_models.add_argument("--provider", default=None, help="Filter to one provider.")

    p_auth = sub.add_parser("auth", help="Manage stored provider API keys (~/.pya/auth.json).")
    auth_sub = p_auth.add_subparsers(dest="auth_command")
    p_set = auth_sub.add_parser("set", help="Store an API key for a provider (prompts if --key omitted).")
    p_set.add_argument("provider", help="Provider id, e.g. anthropic or openai.")
    p_set.add_argument("--key", default=None, help="The key (omit to be prompted, hidden).")
    auth_sub.add_parser("list", help="List providers with a stored credential.")
    p_rm = auth_sub.add_parser("remove", help="Remove a provider's stored credential.")
    p_rm.add_argument("provider")

    p_config = sub.add_parser("config", help="View/edit non-secret settings (~/.pya/settings.toml).")
    cfg_sub = p_config.add_subparsers(dest="config_command")
    cfg_sub.add_parser("show", help="Show current settings.")
    pdef = cfg_sub.add_parser("set-default", help="Set the default model (provider/model).")
    pdef.add_argument("model", metavar="provider/model")
    pmodels = cfg_sub.add_parser("models", help="Set a provider's model allowlist (omit models to clear it / enable with built-ins).")
    pmodels.add_argument("provider")
    pmodels.add_argument("models", nargs="*", help="Model ids to allow (none = clear the allowlist).")
    pcrm = cfg_sub.add_parser("remove-provider", help="Remove a provider from settings.")
    pcrm.add_argument("provider")

    return parser


def _cmd_config(args) -> int:
    from .settings import ProviderConfig, Settings, SETTINGS_PATH, load, save

    s = load()
    if args.config_command in (None, "show"):
        if not (s.default_model or s.providers):
            print(f"(no settings in {SETTINGS_PATH})")
            return 0
        if s.default_provider and s.default_model:
            print(f"default = {s.default_provider}/{s.default_model}")
        for name in sorted(s.providers):
            cfg = s.providers[name]
            key = f" key=…{cfg.api_key[-4:]}" if cfg.api_key else ""
            models = (" models=" + ", ".join(cfg.models)) if cfg.models else " models=(built-ins)"
            print(f"[{name}]{key}{models}")
        return 0

    providers = dict(s.providers)
    if args.config_command == "set-default":
        if "/" not in args.model:
            print("[error] expected provider/model, e.g. anthropic/claude-opus-4-8", file=sys.stderr)
            return 1
        dp, dm = args.model.split("/", 1)
        save(Settings(default_provider=dp, default_model=dm, providers=providers))
        print(f"default = {dp}/{dm}")
        return 0
    if args.config_command == "models":
        existing = providers.get(args.provider, ProviderConfig())
        providers[args.provider] = ProviderConfig(api_key=existing.api_key, models=tuple(args.models))
        save(Settings(default_provider=s.default_provider, default_model=s.default_model, providers=providers))
        print(f"{args.provider}: " + (", ".join(args.models) if args.models else "(built-ins)"))
        return 0
    if args.config_command == "remove-provider":
        if providers.pop(args.provider, None) is None:
            print(f"No provider {args.provider} in settings.")
            return 0
        save(Settings(default_provider=s.default_provider, default_model=s.default_model, providers=providers))
        print(f"Removed provider {args.provider}.")
        return 0
    return 0


def _cmd_auth(args) -> int:
    import getpass

    from .providers import oauth

    if args.auth_command == "set":
        key = args.key or getpass.getpass(f"API key for {args.provider}: ").strip()
        if not key:
            print("[error] no key provided", file=sys.stderr)
            return 1
        oauth.set_api_key(args.provider, key)
        print(f"Stored key for {args.provider} (…{key[-4:]}) in ~/.pya/auth.json")
        return 0
    if args.auth_command == "remove":
        print(f"Removed {args.provider}." if oauth.clear_token(args.provider) else f"No stored credential for {args.provider}.")
        return 0
    # default / "list"
    creds = oauth.list_credentials()
    if not creds:
        print("(no stored credentials)")
    for provider, kind in sorted(creds.items()):
        print(f"{provider:16} {kind}")
    return 0


def _cmd_models(provider: str | None, cwd: str) -> int:
    """List available models: the curated built-in catalog plus any custom/local models
    from ``~/.pya/models.json`` / ``<cwd>/.pya/models.json``. No network call."""
    from .models_registry import load_model_registry, merge_catalog
    from .settings import catalog_models

    models = merge_catalog(catalog_models(), load_model_registry(cwd))
    if provider is not None:
        models = [m for m in models if m.provider == provider]
    if not models:
        print("(no models)", file=sys.stderr)
        return 1
    for m in models:
        tag = "  [custom]" if m.is_custom else ""
        print(f"{m.label}{tag}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "models":
        return _cmd_models(args.provider, args.cwd)
    if args.command == "auth":
        return _cmd_auth(args)
    if args.command == "config":
        return _cmd_config(args)

    # Default: one-shot if -p was given, otherwise the interactive REPL.
    from .app import run
    from .settings import load as load_settings

    settings = load_settings()
    provider = args.provider or settings.default_provider or DEFAULT_PROVIDER
    model = args.model or settings.default_model or DEFAULT_MODEL

    permission_mode = "bypass" if args.yolo else args.permission_mode
    return run(
        provider=provider,
        model=model,
        reasoning=args.reasoning,
        cwd=args.cwd,
        prompt=args.prompt,
        permission_mode=permission_mode,
        continue_session=args.continue_session,
        resume=args.resume,
        no_session=args.no_session,
        max_retries=args.max_retries,
        compact=not args.no_compact,
        context_window=args.context_window,
        subagent=not args.no_subagent,
    )


if __name__ == "__main__":
    raise SystemExit(main())
