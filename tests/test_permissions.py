"""Permission decisions across modes and rules."""

from __future__ import annotations

from agent.permissions import PermissionMode, Permissions


def test_read_only_tools_always_allowed():
    p = Permissions()
    assert p.decide("read", {"path": "x"}) == "allow"
    assert p.decide("grep", {"pattern": "x"}) == "allow"
    assert p.decide("ls", {}) == "allow"


def test_default_asks_for_mutating_tools():
    p = Permissions()
    assert p.decide("write", {"path": "x"}) == "ask"
    assert p.decide("edit", {"path": "x"}) == "ask"
    assert p.decide("bash", {"command": "ls"}) == "ask"


def test_bypass_allows_everything():
    p = Permissions(mode=PermissionMode.BYPASS)
    assert p.decide("bash", {"command": "rm -rf /"}) == "allow"


def test_plan_denies_mutations_allows_reads():
    p = Permissions(mode=PermissionMode.PLAN)
    assert p.decide("write", {"path": "x"}) == "deny"
    assert p.decide("read", {"path": "x"}) == "allow"


def test_accept_edits_allows_edits_but_asks_bash():
    p = Permissions(mode=PermissionMode.ACCEPT_EDITS)
    assert p.decide("write", {"path": "x"}) == "allow"
    assert p.decide("edit", {"path": "x"}) == "allow"
    assert p.decide("bash", {"command": "ls"}) == "ask"


def test_deny_rule_beats_mode_and_allow():
    p = Permissions(mode=PermissionMode.BYPASS, deny=["bash(rm *)"])
    assert p.decide("bash", {"command": "rm -rf x"}) == "deny"
    assert p.decide("bash", {"command": "ls"}) == "allow"


def test_allow_rule_with_command_glob():
    p = Permissions(allow=["bash(git *)"])
    assert p.decide("bash", {"command": "git status"}) == "allow"
    assert p.decide("bash", {"command": "npm install"}) == "ask"


def test_allow_rule_with_path_glob():
    p = Permissions(allow=["write(src/*)"])
    assert p.decide("write", {"path": "src/x.py"}) == "allow"
    assert p.decide("write", {"path": "secrets.txt"}) == "ask"


def test_allow_always_remembers_bash_prefix():
    p = Permissions()
    assert p.decide("bash", {"command": "git status"}) == "ask"
    rule = p.allow_always("bash", {"command": "git status"})
    assert rule == "bash(git *)"
    assert p.decide("bash", {"command": "git log"}) == "allow"
    assert p.decide("bash", {"command": "npm i"}) == "ask"


def test_allow_always_for_non_bash_uses_tool_name():
    p = Permissions()
    assert p.allow_always("write", {"path": "a.py"}) == "write"
    assert p.decide("write", {"path": "anything.py"}) == "allow"
