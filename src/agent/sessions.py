"""Session persistence — save and resume conversations as JSONL.

Port reference: ``packages/agent/src/harness/session/`` (Pi uses a *tree* of entries;
this is the simpler **linear log** the plan recommends for an example — one file per
session, one JSON object per line).

Layout: ``~/.pya/sessions/<id>.jsonl`` (override the root with ``PYA_SESSIONS_DIR``).
The first line is a header; each later line wraps one wire message::

    {"type": "session", "id": ..., "cwd": ..., "created": <ms>, "model": "anthropic/..."}
    {"type": "message", "data": {"role": "user", ...}}
    {"type": "message", "data": {"role": "assistant", ...}}

Sessions are filtered by working directory via the ``cwd`` in the header, so ``--continue``
resumes the most recent conversation *for this project*.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from .types import AgentMessage, message_from_wire, message_to_wire, now_ms

__all__ = ["Session", "SessionStore", "SessionInfo", "sessions_root"]


def sessions_root() -> Path:
    """The directory sessions live in (``PYA_SESSIONS_DIR`` or ``~/.pya/sessions``)."""
    env = os.environ.get("PYA_SESSIONS_DIR")
    return Path(env) if env else Path.home() / ".pya" / "sessions"


@dataclass
class SessionInfo:
    """Summary of a stored session (for listing)."""

    id: str
    path: Path
    cwd: str
    created: int
    model: str | None
    messages: int
    preview: str


class Session:
    """A handle to one session file. Appends are tracked so only new messages are written."""

    def __init__(self, path: Path, id: str, count: int = 0) -> None:
        self.path = path
        self.id = id
        self.count = count  # messages already written to disk

    def append(self, message: AgentMessage) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "message", "data": message_to_wire(message)}) + "\n")
        self.count += 1

    def append_new(self, history: list[AgentMessage]) -> None:
        """Persist any messages in ``history`` not yet written."""
        for message in history[self.count :]:
            self.append(message)


class SessionStore:
    """Creates, loads, and lists sessions under a root directory."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or sessions_root()

    def create(self, cwd: str | Path, model: str | None) -> Session:
        self.root.mkdir(parents=True, exist_ok=True)
        session_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        path = self.root / f"{session_id}.jsonl"
        header = {
            "type": "session",
            "id": session_id,
            "cwd": str(Path(cwd).resolve()),
            "created": now_ms(),
            "model": model,
        }
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(header) + "\n")
        return Session(path, session_id)

    def load(self, id_or_path: str | Path) -> tuple[dict, list[AgentMessage], Session]:
        """Return (header, messages, session) for an existing session."""
        path = self._resolve(id_or_path)
        header, messages = self._read(path)
        return header, messages, Session(path, header.get("id", path.stem), count=len(messages))

    def list(self, cwd: str | Path | None = None, *, limit: int = 20) -> list[SessionInfo]:
        """Recent sessions (newest first), optionally filtered to one working directory."""
        if not self.root.is_dir():
            return []
        wanted = str(Path(cwd).resolve()) if cwd is not None else None
        infos: list[SessionInfo] = []
        for path in self.root.glob("*.jsonl"):
            try:
                header, messages = self._read(path)
            except (OSError, json.JSONDecodeError):
                continue
            if wanted is not None and header.get("cwd") != wanted:
                continue
            preview = next(
                (getattr(m, "content", "") for m in messages if getattr(m, "role", None) == "user"),
                "",
            )
            infos.append(
                SessionInfo(
                    id=header.get("id", path.stem),
                    path=path,
                    cwd=header.get("cwd", ""),
                    created=header.get("created", 0),
                    model=header.get("model"),
                    messages=len(messages),
                    preview=str(preview)[:60],
                )
            )
        infos.sort(key=lambda info: info.created, reverse=True)
        return infos[:limit]

    def latest(self, cwd: str | Path) -> str | None:
        infos = self.list(cwd, limit=1)
        return infos[0].id if infos else None

    # -- internals --------------------------------------------------------

    def _resolve(self, id_or_path: str | Path) -> Path:
        path = Path(id_or_path)
        if path.exists():
            return path
        candidate = self.root / f"{id_or_path}.jsonl"
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"session not found: {id_or_path}")

    @staticmethod
    def _read(path: Path) -> tuple[dict, list[AgentMessage]]:
        header: dict = {}
        messages: list[AgentMessage] = []
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("type") == "session":
                    header = obj
                elif obj.get("type") == "message":
                    messages.append(message_from_wire(obj["data"]))
        return header, messages
