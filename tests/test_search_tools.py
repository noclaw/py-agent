"""grep / find / ls tools, against a temp directory."""

from __future__ import annotations

from agent.tools.find import FindArgs, FindTool
from agent.tools.grep import GrepArgs, GrepTool
from agent.tools.ls import LsArgs, LsTool


def _populate(root):
    (root / "a.py").write_text("import os\nprint('hello')\n")
    (root / "b.txt").write_text("hello world\nGOODBYE\n")
    sub = root / "sub"
    sub.mkdir()
    (sub / "c.py").write_text("x = 1\nprint('hi')\n")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("print('should be skipped')\n")


# --- grep ------------------------------------------------------------------


async def test_grep_finds_matches(tmp_path):
    _populate(tmp_path)
    result = await GrepTool(tmp_path).execute(GrepArgs(pattern=r"print\("))
    assert not result.is_error
    assert "a.py:2" in result.content
    assert "sub/c.py:2" in result.content
    assert ".git" not in result.content  # skipped


async def test_grep_glob_filter(tmp_path):
    _populate(tmp_path)
    result = await GrepTool(tmp_path).execute(GrepArgs(pattern="print", glob="*.py"))
    assert "a.py" in result.content
    assert "b.txt" not in result.content


async def test_grep_ignore_case(tmp_path):
    _populate(tmp_path)
    result = await GrepTool(tmp_path).execute(GrepArgs(pattern="goodbye", ignore_case=True))
    assert "b.txt" in result.content


async def test_grep_no_matches(tmp_path):
    _populate(tmp_path)
    result = await GrepTool(tmp_path).execute(GrepArgs(pattern="zzzznotfound"))
    assert "no matches" in result.content


async def test_grep_invalid_regex(tmp_path):
    result = await GrepTool(tmp_path).execute(GrepArgs(pattern="("))
    assert result.is_error and "Invalid regex" in result.content


# --- find ------------------------------------------------------------------


async def test_find_recursive_glob(tmp_path):
    _populate(tmp_path)
    result = await FindTool(tmp_path).execute(FindArgs(pattern="**/*.py"))
    assert "a.py" in result.content
    assert "sub/c.py" in result.content


async def test_find_skips_noise_dirs(tmp_path):
    _populate(tmp_path)
    result = await FindTool(tmp_path).execute(FindArgs(pattern="**/*"))
    assert "config" not in result.content  # under .git


async def test_find_no_match(tmp_path):
    _populate(tmp_path)
    result = await FindTool(tmp_path).execute(FindArgs(pattern="*.rs"))
    assert "no files" in result.content


# --- ls --------------------------------------------------------------------


async def test_ls_lists_entries_with_dir_suffix(tmp_path):
    _populate(tmp_path)
    result = await LsTool(tmp_path).execute(LsArgs())
    assert "a.py" in result.content
    assert "sub/" in result.content  # directory marked


async def test_ls_missing_dir(tmp_path):
    result = await LsTool(tmp_path).execute(LsArgs(path="nope"))
    assert result.is_error
