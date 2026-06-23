"""The agent loop (Phase 5) — the heart of the agent.

Port target: ``packages/agent/src/agent-loop.ts``.

Will implement the nested turn loop: stream the assistant response, collect tool calls,
execute them (parallel by default; sequential when a tool requires it), feed tool results
back into history, and repeat until there are no tool calls and no queued messages. Emits
the event taxonomy from :mod:`coding_agent.types` for the renderer, supports cooperative
cancellation (propagated to the model stream and running tools), and exposes hooks
(before/after tool call, transform-context) that later phases use for permissions and
compaction.

The single most valuable test fixture here is a *fake model* (scripted event sequences)
so the loop is testable without the network.
"""

from __future__ import annotations
