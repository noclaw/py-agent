"""Command-line entry point (``pycoda``).

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
        prog="pycoda",
        description="A readable Python coding agent (model layer via pi-py/pi-ai).",
    )
    parser.add_argument("--version", action="version", version=f"pycoda {__version__}")
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

    # Default: launch the interactive app (currently a roadmap stub).
    from .app import run

    return run(provider=args.provider, model=args.model)


if __name__ == "__main__":
    raise SystemExit(main())
