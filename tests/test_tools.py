"""Phase 4: the built-in tools, against a temp directory."""

from __future__ import annotations

from agent.tools.bash import BashArgs, BashTool
from agent.tools.edit import EditArgs, EditOp, EditTool
from agent.tools.read import ReadArgs, ReadTool
from agent.tools.write import WriteArgs, WriteTool


# --- read ------------------------------------------------------------------


async def test_read_returns_contents(tmp_path):
    (tmp_path / "f.txt").write_text("line1\nline2\nline3\n")
    result = await ReadTool(tmp_path).execute(ReadArgs(path="f.txt"))
    assert not result.is_error
    assert "line1" in result.content and "line3" in result.content


async def test_read_offset_and_limit(tmp_path):
    (tmp_path / "f.txt").write_text("a\nb\nc\nd\n")
    result = await ReadTool(tmp_path).execute(ReadArgs(path="f.txt", offset=2, limit=2))
    assert result.content == "b\nc"


async def test_read_missing_file_errors(tmp_path):
    result = await ReadTool(tmp_path).execute(ReadArgs(path="nope.txt"))
    assert result.is_error and "not found" in result.content.lower()


# --- write -----------------------------------------------------------------


async def test_write_creates_parent_dirs(tmp_path):
    result = await WriteTool(tmp_path).execute(WriteArgs(path="sub/dir/f.txt", content="hello"))
    assert not result.is_error
    assert (tmp_path / "sub" / "dir" / "f.txt").read_text() == "hello"


async def test_write_overwrites(tmp_path):
    (tmp_path / "f.txt").write_text("old")
    await WriteTool(tmp_path).execute(WriteArgs(path="f.txt", content="new"))
    assert (tmp_path / "f.txt").read_text() == "new"


# --- edit ------------------------------------------------------------------


async def test_edit_replaces_unique_text(tmp_path):
    (tmp_path / "f.txt").write_text("alpha\nbeta\ngamma\n")
    result = await EditTool(tmp_path).execute(
        EditArgs(path="f.txt", edits=[EditOp(old_text="beta", new_text="BETA")])
    )
    assert not result.is_error
    assert (tmp_path / "f.txt").read_text() == "alpha\nBETA\ngamma\n"
    assert "diff" in (result.details or {})


async def test_edit_ambiguous_match_errors(tmp_path):
    (tmp_path / "f.txt").write_text("x x x")
    result = await EditTool(tmp_path).execute(
        EditArgs(path="f.txt", edits=[EditOp(old_text="x", new_text="y")])
    )
    assert result.is_error and "unique" in result.content
    assert (tmp_path / "f.txt").read_text() == "x x x"  # unchanged


async def test_edit_missing_text_errors(tmp_path):
    (tmp_path / "f.txt").write_text("hello")
    result = await EditTool(tmp_path).execute(
        EditArgs(path="f.txt", edits=[EditOp(old_text="absent", new_text="z")])
    )
    assert result.is_error and "not found" in result.content


# --- bash ------------------------------------------------------------------


async def test_bash_runs_command(tmp_path):
    result = await BashTool(tmp_path).execute(BashArgs(command="echo hello"))
    assert not result.is_error
    assert "hello" in result.content


async def test_bash_nonzero_exit_is_error(tmp_path):
    result = await BashTool(tmp_path).execute(BashArgs(command="exit 3"))
    assert result.is_error and "exit code 3" in result.content


async def test_bash_runs_in_cwd(tmp_path):
    (tmp_path / "marker.txt").write_text("x")
    result = await BashTool(tmp_path).execute(BashArgs(command="ls"))
    assert "marker.txt" in result.content


async def test_bash_timeout(tmp_path):
    result = await BashTool(tmp_path).execute(BashArgs(command="sleep 5", timeout=0.5))
    assert result.is_error and "timed out" in result.content
