"""The fuzzy picker's pure parts: scoring, filtering, and the non-TTY fallback."""

from __future__ import annotations

import builtins

from agent import picker


def test_fuzzy_score_subsequence():
    # "gpt5" matches "gpt-5.1" but not "claude".
    assert picker.fuzzy_score("openai/gpt-5.1", "gpt5") is not None
    assert picker.fuzzy_score("anthropic/claude-opus", "gpt5") is None


def test_fuzzy_score_prefers_contiguous_and_early():
    options = ["a-g-p-t-5-x", "gpt5zzz", "zzzgpt5"]
    ranked = picker.filter_options(options, "gpt5")
    # The contiguous, front-anchored match ranks first.
    assert options[ranked[0]] == "gpt5zzz"
    assert set(ranked) == {0, 1, 2}  # all three contain the subsequence


def test_filter_empty_query_keeps_all_in_order():
    options = ["b", "a", "c"]
    assert picker.filter_options(options, "") == [0, 1, 2]


def test_filter_no_match():
    assert picker.filter_options(["abc", "def"], "xyz") == []


def test_select_non_tty_uses_numbered_fallback(monkeypatch, capsys):
    # Force the fallback path (no real terminal) and feed a chosen number.
    monkeypatch.setattr(picker.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(builtins, "input", lambda *a, **k: "2")
    choice = picker.select(["openai/gpt-5.1", "anthropic/claude-opus-4-8"], prompt="Pick")
    assert choice == "anthropic/claude-opus-4-8"


def test_select_non_tty_blank_cancels(monkeypatch):
    monkeypatch.setattr(picker.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(builtins, "input", lambda *a, **k: "")
    assert picker.select(["a", "b"], prompt="Pick") is None


def test_select_empty_options_returns_none():
    assert picker.select([]) is None


# --- the interactive termios path, driven through a real pseudo-terminal ---------

import os

import pytest

_POSIX = os.name == "posix" and hasattr(os, "fork")
if _POSIX:
    import pty


def _drive_picker(keys: list[bytes], timeout: float = 5.0) -> str:
    """Run the picker in a child attached to a PTY, feed ``keys``, return its choice."""
    import select as _sel
    import time

    options = ["anthropic/claude-opus-4-8", "anthropic/claude-sonnet-4-6", "openai/gpt-5.1", "local/qwen3"]
    pid, fd = pty.fork()
    if pid == 0:  # child: fds 0/1/2 are the PTY; rebind sys.std* past pytest's capture
        import sys as _sys

        _sys.stdin = os.fdopen(0, "r")
        _sys.stdout = os.fdopen(1, "w")
        choice = picker.select(options, current="anthropic/claude-sonnet-4-6", prompt="Select")
        os.write(1, f"\n@@R@@{choice}\n".encode())
        os._exit(0)

    time.sleep(0.3)
    for k in keys:
        os.write(fd, k)
        time.sleep(0.15)
    out = b""
    end = time.time() + timeout
    while time.time() < end and b"@@R@@" not in out:
        r, _, _ = _sel.select([fd], [], [], 0.2)
        if r:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
    os.waitpid(pid, 0)
    text = out.decode(errors="replace")
    return text.split("@@R@@", 1)[1].strip().splitlines()[0] if "@@R@@" in text else "(none)"


@pytest.mark.skipif(not _POSIX, reason="PTY-driven test needs a POSIX fork")
def test_interactive_filter_and_select():
    assert _drive_picker([b"qwen", b"\r"]) == "local/qwen3"  # fuzzy filter + Enter
    assert _drive_picker([b"\x1b[B", b"\x1b[B", b"\r"]) == "openai/gpt-5.1"  # Down Down Enter
    assert _drive_picker([b"\x1b"]) == "None"  # Esc cancels
