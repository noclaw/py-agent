"""Persistent permission rules (PLAN #6) — .pya/permissions.json round-trips."""

from __future__ import annotations

import json

from agent.permissions import PermissionMode, Permissions, PermissionStore


def _store(tmp_path) -> PermissionStore:
    return PermissionStore(tmp_path / ".pya" / "permissions.json")


def test_store_save_and_load(tmp_path):
    store = _store(tmp_path)
    assert store.load() == ([], [])  # missing file → empty
    store.save(["bash(git *)"], ["write(secret/*)"])
    assert store.path.exists()
    assert store.load() == (["bash(git *)"], ["write(secret/*)"])


def test_store_ignores_malformed(tmp_path):
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not json", encoding="utf-8")
    assert store.load() == ([], [])


def test_allow_always_persists(tmp_path):
    store = _store(tmp_path)
    perms = Permissions(store=store)
    perms.allow_always("bash", {"command": "git status"})
    assert "bash(git *)" in perms.allow
    # written through to disk
    assert store.load() == (["bash(git *)"], [])


def test_allow_always_without_store_does_not_crash():
    perms = Permissions()  # no store
    rule = perms.allow_always("bash", {"command": "ls -la"})
    assert rule in perms.allow  # still tracked in-memory


def test_load_seeds_from_disk_and_keeps_store(tmp_path):
    _store(tmp_path).save(["read"], ["bash(rm *)"])
    perms = Permissions.load(tmp_path, mode=PermissionMode.DEFAULT)
    assert perms.allow == ["read"] and perms.deny == ["bash(rm *)"]
    # a denied command is blocked using the persisted rule
    assert perms.decide("bash", {"command": "rm -rf x"}) == "deny"
    # new always-rules persist back through the attached store
    perms.allow_always("bash", {"command": "git log"})
    allow, _ = PermissionStore.for_cwd(tmp_path).load()
    assert "bash(git *)" in allow


def test_add_remove_clear_rules(tmp_path):
    perms = Permissions.load(tmp_path)
    assert perms.add_rule("allow", "edit(src/*)") is True
    assert perms.add_rule("allow", "edit(src/*)") is False  # idempotent
    assert perms.add_rule("deny", "bash(curl *)") is True
    assert perms.remove_rule("edit(src/*)") is True
    assert perms.remove_rule("nope") is False
    # everything persisted
    data = json.loads((tmp_path / ".pya" / "permissions.json").read_text())
    assert data == {"allow": [], "deny": ["bash(curl *)"]}
    perms.clear_rules()
    assert perms.allow == [] and perms.deny == []
    assert json.loads((tmp_path / ".pya" / "permissions.json").read_text()) == {"allow": [], "deny": []}


def test_persisted_allow_rule_is_honored(tmp_path):
    perms = Permissions.load(tmp_path)
    perms.add_rule("allow", "bash(git *)")
    # reload from disk in a fresh Permissions, simulating a new session
    reloaded = Permissions.load(tmp_path)
    assert reloaded.decide("bash", {"command": "git status"}) == "allow"
    assert reloaded.decide("bash", {"command": "rm -rf /"}) == "ask"
