"""A tiny dependency-free fuzzy selector for the terminal.

Used by ``/model`` to pick a model interactively: type to filter (subsequence match),
``↑``/``↓`` to move, ``Enter`` to choose, ``Esc``/``Ctrl-C`` to cancel. It's a small,
readable stand-in for a TUI library — raw-mode key handling on Unix, with a graceful
numbered-prompt fallback when stdin/stdout isn't a TTY (pipes, tests, Windows).

The matcher and the fallback are pure functions so they're easy to test; only
:func:`select` touches the terminal.
"""

from __future__ import annotations

import sys
from typing import Sequence

__all__ = ["select", "fuzzy_score", "filter_options"]


def fuzzy_score(option: str, query: str) -> int | None:
    """Subsequence match score for ``query`` against ``option`` (lower is better).

    Returns ``None`` if ``query``'s characters don't appear in order in ``option``. The
    score rewards earlier and more contiguous matches, so ``gpt5`` ranks ``gpt-5`` above
    ``g…p…t…5`` spread across the string. Case-insensitive; spaces in the query are ignored.
    """
    q = query.lower().replace(" ", "")
    if not q:
        return 0
    text = option.lower()
    score = 0
    pos = -1
    for ch in q:
        nxt = text.find(ch, pos + 1)
        if nxt == -1:
            return None
        score += nxt - pos - 1  # gap since the previous matched char (0 = contiguous)
        if pos == -1:
            score += nxt  # reward matches that start near the front
        pos = nxt
    return score


def filter_options(options: Sequence[str], query: str) -> list[int]:
    """Indices of ``options`` matching ``query``, best match first (stable on ties)."""
    scored = [(s, i) for i, opt in enumerate(options) if (s := fuzzy_score(opt, query)) is not None]
    scored.sort(key=lambda si: (si[0], si[1]))
    return [i for _, i in scored]


def _numbered_select(options: Sequence[str], *, current: str | None, prompt: str) -> str | None:
    """Fallback for non-interactive stdin: print a numbered list and read a choice."""
    out = sys.stderr
    out.write(f"{prompt}\n")
    for i, opt in enumerate(options, 1):
        mark = "  * current" if opt == current else ""
        out.write(f"  {i:>3}  {opt}{mark}\n")
    out.flush()
    try:
        raw = input("number (or blank to cancel): ").strip()
    except EOFError:
        return None
    if not raw:
        return None
    try:
        idx = int(raw)
    except ValueError:
        return None
    return options[idx - 1] if 1 <= idx <= len(options) else None


def select(
    options: Sequence[str],
    *,
    current: str | None = None,
    prompt: str = "Select",
    max_visible: int = 12,
) -> str | None:
    """Interactively pick one of ``options``; return it, or ``None`` if cancelled."""
    options = list(options)
    if not options:
        return None
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return _numbered_select(options, current=current, prompt=prompt)
    try:
        import termios
        import tty
    except ImportError:  # non-Unix
        return _numbered_select(options, current=current, prompt=prompt)

    return _interactive_select(options, current=current, prompt=prompt, max_visible=max_visible,
                               termios=termios, tty=tty)


def _read_key(fd: int) -> str:
    """Read one logical keypress, decoding arrow escape sequences."""
    import os
    import select as _select

    ch = os.read(fd, 1)
    if ch == b"\x1b":
        # Could be a bare Esc or an arrow (\x1b[A …). Peek without blocking.
        ready, _, _ = _select.select([fd], [], [], 0.02)
        if not ready:
            return "esc"
        seq = os.read(fd, 2)
        return {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left"}.get(seq, "esc")
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch in (b"\x7f", b"\x08"):
        return "backspace"
    if ch == b"\x03":
        return "ctrl-c"
    try:
        return ch.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _interactive_select(options, *, current, prompt, max_visible, termios, tty) -> str | None:
    fd = sys.stdin.fileno()
    out = sys.stdout
    query = ""
    selected = 0
    drawn = 0  # number of lines the previous frame occupied

    def _block() -> list[str]:
        nonlocal selected
        matches = filter_options(options, query)
        selected = max(0, min(selected, len(matches) - 1)) if matches else 0
        # Scroll a window so the selection stays visible.
        start = max(0, min(selected - max_visible // 2, max(0, len(matches) - max_visible)))
        window = matches[start:start + max_visible]

        lines = [f"{prompt}  \x1b[2m(type to filter, ↑/↓ move, Enter select, Esc cancel)\x1b[0m",
                 f"> {query}\x1b[7m \x1b[0m"]
        for row, idx in enumerate(window):
            opt = options[idx]
            mark = " \x1b[2m* current\x1b[0m" if opt == current else ""
            pointer = "\x1b[36m❯ " if start + row == selected else "  \x1b[2m"
            lines.append(f"{pointer}{opt}\x1b[0m{mark}")
        if not matches:
            lines.append("  \x1b[2m(no matches)\x1b[0m")
        return lines

    def draw() -> None:
        nonlocal drawn
        if drawn:
            out.write(f"\x1b[{drawn - 1}A")  # back to the first line of the block
        out.write("\r\x1b[0J")  # clear from cursor to end of screen, then redraw
        lines = _block()
        out.write("\n".join(lines))
        out.write("\r")
        out.flush()
        drawn = len(lines)

    def clear() -> None:
        if drawn:
            out.write(f"\x1b[{drawn - 1}A\r\x1b[0J")
            out.flush()

    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            draw()
            key = _read_key(fd)
            if key in ("ctrl-c", "esc"):
                return None
            if key == "enter":
                matches = filter_options(options, query)
                return options[matches[selected]] if matches else None
            if key == "up":
                selected -= 1
            elif key == "down":
                selected += 1
            elif key == "backspace":
                query = query[:-1]
                selected = 0
            elif key and key.isprintable():
                query += key
                selected = 0
    finally:
        clear()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out.flush()
