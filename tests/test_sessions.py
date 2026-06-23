"""Session persistence: save, load, list, and message reconstruction."""

from __future__ import annotations

from agent.sessions import SessionStore
from agent.types import (
    ToolResultMessage,
    UserMessage,
    tool_result_message,
    user_message,
)
from pi_py_sdk import AssistantMessage


def _store(tmp_path):
    return SessionStore(root=tmp_path / "sessions")


def _sample_history():
    assistant = AssistantMessage(
        role="assistant",
        content=[
            {"type": "text", "text": "reading it"},
            {"type": "toolCall", "id": "c1", "name": "read", "arguments": {"path": "a.py"}},
        ],
        stopReason="toolUse",
    )
    return [
        user_message("read a.py"),
        assistant,
        tool_result_message("c1", "read", "print('hi')"),
    ]


def test_round_trip_preserves_messages(tmp_path):
    store = _store(tmp_path)
    session = store.create(tmp_path, "anthropic/claude-sonnet-4-6")
    history = _sample_history()
    session.append_new(history)

    _header, loaded, _session = store.load(session.id)
    assert [type(m).__name__ for m in loaded] == ["UserMessage", "AssistantMessage", "ToolResultMessage"]
    assert isinstance(loaded[0], UserMessage) and loaded[0].content == "read a.py"
    # Assistant message keeps its tool-call block.
    assert loaded[1].content[1]["name"] == "read"
    assert loaded[1].stopReason == "toolUse"
    tr = loaded[2]
    assert isinstance(tr, ToolResultMessage)
    assert tr.tool_call_id == "c1" and tr.tool_name == "read" and tr.content == "print('hi')"


def test_append_new_only_writes_unwritten(tmp_path):
    store = _store(tmp_path)
    session = store.create(tmp_path, None)
    history = [user_message("one")]
    session.append_new(history)
    assert session.count == 1
    history.append(user_message("two"))
    session.append_new(history)  # only "two" is new
    assert session.count == 2
    _h, loaded, _s = store.load(session.id)
    assert [m.content for m in loaded] == ["one", "two"]


def test_header_records_cwd_and_model(tmp_path):
    store = _store(tmp_path)
    session = store.create(tmp_path, "anthropic/claude-haiku-4-5")
    header, _loaded, _s = store.load(session.id)
    assert header["cwd"] == str(tmp_path.resolve())
    assert header["model"] == "anthropic/claude-haiku-4-5"


def test_list_filters_by_cwd_and_sorts_newest_first(tmp_path):
    store = _store(tmp_path)
    a = store.create(tmp_path / "proj_a", None)
    a.append(user_message("first project"))
    b = store.create(tmp_path / "proj_b", None)
    b.append(user_message("second project"))

    infos_a = store.list(tmp_path / "proj_a")
    assert [i.id for i in infos_a] == [a.id]
    assert infos_a[0].preview == "first project"

    all_infos = store.list()
    assert {i.id for i in all_infos} == {a.id, b.id}


def test_latest_returns_a_session_for_cwd(tmp_path):
    store = _store(tmp_path)
    assert store.latest(tmp_path) is None  # none yet
    session = store.create(tmp_path, None)
    session.append(user_message("hi"))
    assert store.latest(tmp_path) == session.id
    # A session in a different cwd isn't picked up.
    assert store.latest(tmp_path / "other") is None


def test_load_missing_raises(tmp_path):
    store = _store(tmp_path)
    try:
        store.load("does-not-exist")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")
