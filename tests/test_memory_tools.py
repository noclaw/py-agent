"""The memory / second-brain tools (note/recall/search_memory) over a temp store."""

from __future__ import annotations

from pathlib import Path

from agent.tools import coding_tools, memory_tools
from agent.tools.memory import (
    NoteArgs,
    NoteTool,
    RecallArgs,
    RecallTool,
    SearchMemoryArgs,
    SearchMemoryTool,
    default_store,
)


def _store(tmp_path) -> Path:
    return tmp_path / "memory.md"


# --- note ------------------------------------------------------------------


async def test_note_creates_store_and_appends(tmp_path):
    store = _store(tmp_path)
    result = await NoteTool(store=store).execute(NoteArgs(text="passport expires in March"))
    assert not result.is_error
    assert store.exists()
    body = store.read_text()
    assert body.startswith("- ")
    assert "passport expires in March" in body


async def test_note_appends_multiple(tmp_path):
    store = _store(tmp_path)
    tool = NoteTool(store=store)
    await tool.execute(NoteArgs(text="first"))
    await tool.execute(NoteArgs(text="second"))
    lines = [ln for ln in store.read_text().splitlines() if ln.startswith("- ")]
    assert len(lines) == 2
    assert "first" in lines[0] and "second" in lines[1]


async def test_note_rejects_empty(tmp_path):
    result = await NoteTool(store=_store(tmp_path)).execute(NoteArgs(text="   "))
    assert result.is_error
    assert not _store(tmp_path).exists()


async def test_note_is_mutating_recall_is_read_only():
    assert NoteTool.read_only is False
    assert RecallTool.read_only is True
    assert SearchMemoryTool.read_only is True
    # note has no path; it gates on the note text.
    assert NoteTool.permission_target({"text": "secret"}) == "secret"


# --- recall ----------------------------------------------------------------


async def test_recall_empty_store(tmp_path):
    result = await RecallTool(store=_store(tmp_path)).execute(RecallArgs())
    assert not result.is_error
    assert "no notes" in result.content.lower()


async def test_recall_returns_recent_newest_last(tmp_path):
    store = _store(tmp_path)
    note = NoteTool(store=store)
    for i in range(5):
        await note.execute(NoteArgs(text=f"note {i}"))
    result = await RecallTool(store=store).execute(RecallArgs(limit=2))
    assert "note 3" in result.content and "note 4" in result.content
    assert "note 0" not in result.content
    assert "most recent 2 of 5" in result.content


# --- search_memory ---------------------------------------------------------


async def test_search_finds_matches(tmp_path):
    store = _store(tmp_path)
    note = NoteTool(store=store)
    await note.execute(NoteArgs(text="dentist appointment Tuesday"))
    await note.execute(NoteArgs(text="buy milk"))
    result = await SearchMemoryTool(store=store).execute(SearchMemoryArgs(query="dentist"))
    assert "dentist appointment" in result.content
    assert "buy milk" not in result.content


async def test_search_no_matches(tmp_path):
    store = _store(tmp_path)
    await NoteTool(store=store).execute(NoteArgs(text="hello"))
    result = await SearchMemoryTool(store=store).execute(SearchMemoryArgs(query="zzz"))
    assert "no matching" in result.content.lower()


async def test_search_case_insensitive_by_default(tmp_path):
    store = _store(tmp_path)
    await NoteTool(store=store).execute(NoteArgs(text="Important Thing"))
    result = await SearchMemoryTool(store=store).execute(SearchMemoryArgs(query="important"))
    assert "Important Thing" in result.content


async def test_search_invalid_regex_errors(tmp_path):
    result = await SearchMemoryTool(store=_store(tmp_path)).execute(SearchMemoryArgs(query="["))
    assert result.is_error and "invalid query" in result.content.lower()


# --- wiring / registry -----------------------------------------------------


def test_memory_tools_bundle(tmp_path):
    tools = memory_tools(store=_store(tmp_path))
    assert [t.name for t in tools] == ["note", "recall", "search_memory"]


def test_memory_tools_are_in_the_default_set():
    names = [t.name for t in coding_tools(".")]
    assert {"note", "recall", "search_memory"} <= set(names)


def test_default_store_honors_env(tmp_path, monkeypatch):
    target = tmp_path / "custom.md"
    monkeypatch.setenv("PYA_MEMORY_FILE", str(target))
    assert default_store() == target
    # constructor with no store uses the env-resolved default
    assert NoteTool().store == target
