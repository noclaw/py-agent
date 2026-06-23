"""Terminal rendering of loop events (Phase 7).

Subscribes to the loop's event stream and renders streaming assistant text/thinking, tool
start/result, and a final usage line. Starts simple with ``rich``; a fuller TUI is an
optional later upgrade. Port reference: ``packages/coding-agent/src/modes/interactive/``.
"""

from __future__ import annotations
