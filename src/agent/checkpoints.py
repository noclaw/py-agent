"""Edit checkpoints — snapshot files before ``write``/``edit`` so a session can rewind.

Each successful `write`/`edit` records the file's *prior* bytes (or ``None`` if the file was
newly created). The REPL can then list checkpoints (`/checkpoints`) and restore the working
tree to an earlier point (`/rewind`), à la Claude Code's checkpoint/rewind — handy for
experimenting under ``--yolo``.

Wiring is two hooks (the loop's `PreToolUse`/`PostToolUse` seams), so the loop and tools are
untouched: `PreToolUse` stashes the current bytes before the tool runs, and `PostToolUse`
commits the checkpoint only if the tool succeeded. State is per-run and in-memory (persisting
across resumes is a future extension); `bash` mutations are not tracked.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .hooks import Hooks

__all__ = ["Checkpoint", "Checkpoints", "register_checkpoint_hooks"]


def _resolve(cwd: Path, path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else (cwd / p)


@dataclass
class Checkpoint:
    """One restorable snapshot: a file's bytes before a ``write``/``edit`` changed it."""

    seq: int
    tool: str  # "write" | "edit"
    path: Path
    before: bytes | None  # prior content; None if the file was created by this call

    @property
    def created(self) -> bool:
        return self.before is None

    def display(self, cwd: Path) -> str:
        try:
            return str(self.path.relative_to(cwd))
        except ValueError:
            return str(self.path)


class Checkpoints:
    """An ordered stack of file snapshots for the current run."""

    def __init__(self) -> None:
        self._items: list[Checkpoint] = []
        self._pending: dict[str, tuple[str, Path, bytes | None]] = {}  # call_id -> (tool, path, before)
        self._seq = 0

    def __len__(self) -> int:
        return len(self._items)

    def list(self) -> list[Checkpoint]:
        return list(self._items)

    # -- capture (driven by the hooks) ------------------------------------

    def stash(self, call_id: str, tool: str, path: Path) -> None:
        """Record the file's current bytes before a tool runs (PreToolUse)."""
        before = path.read_bytes() if path.exists() else None
        self._pending[call_id] = (tool, path, before)

    def commit(self, call_id: str, *, success: bool) -> None:
        """Finalize a stashed snapshot iff the tool succeeded (PostToolUse)."""
        item = self._pending.pop(call_id, None)
        if item is None or not success:
            return
        tool, path, before = item
        self._seq += 1
        self._items.append(Checkpoint(self._seq, tool, path, before))

    # -- restore ----------------------------------------------------------

    def _restore(self, cp: Checkpoint) -> None:
        if cp.before is None:
            if cp.path.exists():
                cp.path.unlink()
        else:
            cp.path.write_bytes(cp.before)

    def undo_last(self) -> Checkpoint | None:
        """Undo the most recent checkpoint; return it (or ``None`` if there are none)."""
        if not self._items:
            return None
        cp = self._items.pop()
        self._restore(cp)
        return cp

    def rewind_to(self, seq: int) -> list[Path]:
        """Undo checkpoint ``seq`` and everything after it. Returns the restored paths."""
        idx = next((i for i, c in enumerate(self._items) if c.seq == seq), None)
        if idx is None:
            return []
        restored: list[Path] = []
        for cp in reversed(self._items[idx:]):  # reverse → each file ends at its earliest `before`
            self._restore(cp)
            restored.append(cp.path)
        del self._items[idx:]
        return restored


def register_checkpoint_hooks(hooks: "Hooks", checkpoints: Checkpoints, cwd: str | Path) -> None:
    """Wire ``checkpoints`` to capture ``write``/``edit`` via the loop's hook seams."""
    base = Path(cwd)

    @hooks.pre_tool_use(matcher="write|edit")
    def _stash(event):  # type: ignore[no-untyped-def]
        path = event.tool_input.get("path")
        if path:
            checkpoints.stash(event.tool_call_id, event.tool_name, _resolve(base, path))
        return None

    @hooks.post_tool_use(matcher="write|edit")
    def _commit(event):  # type: ignore[no-untyped-def]
        checkpoints.commit(event.tool_call_id, success=not event.result.is_error)
        return None
