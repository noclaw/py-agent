"""Edit checkpoints: capture on success, undo/rewind restore, and the hook wiring."""

from __future__ import annotations

import pytest

from agent.checkpoints import Checkpoints, register_checkpoint_hooks
from agent.hooks import Hooks, PostToolUse, PreToolUse
from agent.types import ToolResult


def _capture(cps, call_id, tool, path, *, success=True):
    cps.stash(call_id, tool, path)
    cps.commit(call_id, success=success)


def test_commit_only_on_success(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("v1")
    cps = Checkpoints()
    _capture(cps, "c1", "edit", f, success=False)  # tool failed → no checkpoint
    assert len(cps) == 0
    _capture(cps, "c2", "edit", f, success=True)
    assert len(cps) == 1 and cps.list()[0].before == b"v1"


def test_undo_last_restores_prior_bytes(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("v1")
    cps = Checkpoints()
    _capture(cps, "c1", "edit", f)          # snapshot v1
    f.write_text("v2")                       # the (simulated) edit
    cp = cps.undo_last()
    assert cp is not None and f.read_text() == "v1" and len(cps) == 0


def test_rewind_to_replays_multiple_edits(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("A")
    cps = Checkpoints()
    _capture(cps, "c1", "edit", f); f.write_text("B")   # cp1: before A
    _capture(cps, "c2", "edit", f); f.write_text("C")   # cp2: before B
    # rewind to before cp1 → restore A (reverse replay: B then A)
    restored = cps.rewind_to(1)
    assert f.read_text() == "A" and restored == [f, f] and len(cps) == 0


def test_new_file_checkpoint_is_deleted_on_rewind(tmp_path):
    f = tmp_path / "new.txt"
    cps = Checkpoints()
    _capture(cps, "c1", "write", f)          # file didn't exist → before is None
    f.write_text("created")                  # the write
    assert cps.list()[0].created is True
    cps.undo_last()
    assert not f.exists()


@pytest.mark.asyncio
async def test_hooks_capture_write_and_edit(tmp_path):
    f = tmp_path / "sub" / "file.py"
    f.parent.mkdir()
    f.write_text("old")
    cps = Checkpoints()
    hooks = Hooks()
    register_checkpoint_hooks(hooks, cps, tmp_path)

    # write/edit are matched; the path resolves against cwd.
    await hooks.run(PreToolUse("edit", {"path": "sub/file.py"}, "id1"))
    f.write_text("new")
    await hooks.run(PostToolUse("edit", {"path": "sub/file.py"}, "id1", ToolResult(content="ok")))
    assert len(cps) == 1 and cps.list()[0].before == b"old"

    # a non-file tool isn't matched → no checkpoint
    await hooks.run(PreToolUse("bash", {"command": "rm x"}, "id2"))
    await hooks.run(PostToolUse("bash", {"command": "rm x"}, "id2", ToolResult(content="ok")))
    assert len(cps) == 1

    # a failed edit is stashed but not committed
    await hooks.run(PreToolUse("edit", {"path": "sub/file.py"}, "id3"))
    await hooks.run(PostToolUse("edit", {"path": "sub/file.py"}, "id3", ToolResult(content="boom", is_error=True)))
    assert len(cps) == 1
