"""Interactive REPL and one-shot runner.

Phase 1 is a placeholder that confirms the package is installed and points at the
roadmap. The real implementation (read a line -> run the agent loop to completion ->
stream output, with Ctrl-C abort and a non-interactive one-shot mode) arrives in the
CLI/REPL phase, built on :mod:`coding_agent.loop` and :mod:`coding_agent.render`.
"""

from __future__ import annotations


def run(*, provider: str, model: str) -> int:
    """Entry point for the default command (interactive agent)."""
    print("py-coding-agent — scaffold (Phase 1).")
    print(f"  configured model: {provider}/{model}")
    print()
    print("The interactive agent is not implemented yet. What works today:")
    print("  pycoda models            # list available models (proves the pi-ai pipeline)")
    print("  pycoda models --provider anthropic")
    print()
    print("Next: tools + agent loop (see PLAN.md).")
    return 0
