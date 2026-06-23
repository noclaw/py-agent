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
        default=DEFAULT_MODEL,
        help=f"Model id (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        help=f"Provider id (default: {DEFAULT_PROVIDER}).",
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
        "-p",
        "--print",
        dest="prompt",
        default=None,
        metavar="PROMPT",
        help="Run a single prompt non-interactively and exit (otherwise start a REPL).",
    )

    sub = parser.add_subparsers(dest="command")

    p_models = sub.add_parser("models", help="List available models (stack smoke test).")
    p_models.add_argument("--provider", default=None, help="Filter to one provider.")

    return parser


def _cmd_models(provider: str | None) -> int:
    """List models via the low-level pi-py model client.

    This is a thin smoke test of the pipeline; the model adapter proper arrives in a
    later phase. Needs Node + a local ``pi`` install (for the bundled pi-ai).
    """
    from pi_py_sdk import PiError, PiModelClientSync

    try:
        with PiModelClientSync() as client:
            models = client.list_models(provider)
    except PiError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    if not models:
        print("(no models — check your `pi` install / provider config)", file=sys.stderr)
        return 1
    for model in sorted(models, key=lambda m: (m.get("provider", ""), m.get("id", ""))):
        print(f"{model.get('provider')}/{model.get('id')}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "models":
        return _cmd_models(args.provider)

    # Default: one-shot if -p was given, otherwise the interactive REPL.
    from .app import run

    permission_mode = "bypass" if args.yolo else args.permission_mode
    return run(
        provider=args.provider,
        model=args.model,
        reasoning=args.reasoning,
        cwd=args.cwd,
        prompt=args.prompt,
        permission_mode=permission_mode,
        continue_session=args.continue_session,
        resume=args.resume,
        no_session=args.no_session,
    )


if __name__ == "__main__":
    raise SystemExit(main())
