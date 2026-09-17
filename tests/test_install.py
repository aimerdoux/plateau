"""tests/test_install.py — owner B4 (docs/harness-0.3/PLAN-step3.md "Tests (B4)").

Exercises `plateau.bridge.install`'s Claude Code `settings.json` hook-table merge:
merge idempotent, foreign top-level keys / hook entries preserved untouched,
`--uninstall` removes only our entries, and the backup file is written exactly once.
"""

from __future__ import annotations

import json
import os

import pytest

from plateau.bridge import install


@pytest.fixture
def root(tmp_path):
    return str(tmp_path)


def _settings_path(root: str) -> str:
    return install.settings_path(root, is_global=False)


def _read(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _all_commands(data, event: str):
    return [
        h.get("command")
        for grp in (data.get("hooks", {}).get(event) or [])
        for h in (grp.get("hooks") or [])
    ]


# ---------------------------------------------------------------------------
# merge idempotent
# ---------------------------------------------------------------------------

def test_fresh_install_writes_full_hook_table(root):
    path, changed = install.install_settings(root)
    assert changed is True
    assert path == _settings_path(root)
    data = _read(path)
    for event in ("SessionStart", "PostToolUse", "PreCompact", "Stop", "SessionEnd", "SubagentStop"):
        assert event in data["hooks"], event
    # our own commands mention a recognizable marker
    for event in data["hooks"]:
        for cmd in _all_commands(data, event):
            assert "plateau hook" in cmd or "plateau.cli hook" in cmd


def test_merge_is_idempotent(root):
    _, changed1 = install.install_settings(root)
    before = _read(_settings_path(root))

    path2, changed2 = install.install_settings(root)
    after = _read(path2)

    assert changed1 is True
    assert changed2 is False, "second install must be a no-op (changed=False)"
    assert before == after, "second install must not alter the file"


def test_merge_settings_pure_function_is_idempotent():
    merged1, changed1 = install.merge_settings({})
    merged2, changed2 = install.merge_settings(merged1)
    assert changed1 is True
    assert changed2 is False
    assert merged1 == merged2


def test_session_start_keeps_both_matchers_for_inject(root):
    """A command-only dedup key would collapse SessionStart's `startup|clear` and
    `compact` groups (both run `inject`, differing only by matcher/timeout) into one,
    silently dropping the compact injection hook. Dedup must be keyed on
    (matcher, command)."""
    path, _ = install.install_settings(root)
    data = _read(path)
    matchers_with_inject = {
        grp.get("matcher")
        for grp in data["hooks"]["SessionStart"]
        for h in grp.get("hooks", [])
        if "inject" in h.get("command", "")
    }
    assert "startup|clear" in matchers_with_inject
    assert "compact" in matchers_with_inject


# ---------------------------------------------------------------------------
# foreign entries preserved
# ---------------------------------------------------------------------------

def test_foreign_top_level_keys_and_hook_entries_survive_install(root):
    path = _settings_path(root)
    foreign = {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "env": {"MY_VAR": "1"},
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "python3 my_other_tool.py", "timeout": 5}]}
            ],
        },
    }
    _write(path, foreign)

    install.install_settings(root)
    data = _read(path)

    assert data["permissions"] == {"allow": ["Bash(ls:*)"]}
    assert data["env"] == {"MY_VAR": "1"}
    stop_commands = _all_commands(data, "Stop")
    assert "python3 my_other_tool.py" in stop_commands
    # ours got appended alongside, not instead of
    assert any("plateau hook" in c or "plateau.cli hook" in c for c in stop_commands)


def test_merge_never_removes_or_reorders_foreign_groups(root):
    path = _settings_path(root)
    foreign = {
        "hooks": {
            "PostToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo one", "timeout": 5}]},
                {"matcher": "", "hooks": [{"type": "command", "command": "echo two", "timeout": 5}]},
            ]
        }
    }
    _write(path, foreign)

    install.install_settings(root)
    data = _read(path)
    groups = data["hooks"]["PostToolUse"]
    # the two foreign groups are still there, in their original order, untouched
    assert groups[0]["matcher"] == "Bash"
    assert groups[0]["hooks"][0]["command"] == "echo one"
    assert groups[1]["matcher"] == ""
    assert groups[1]["hooks"][0]["command"] == "echo two"


# ---------------------------------------------------------------------------
# uninstall removes only ours
# ---------------------------------------------------------------------------

def test_uninstall_removes_only_our_entries(root):
    path = _settings_path(root)
    foreign = {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "python3 my_other_tool.py", "timeout": 5}]}
            ],
        },
    }
    _write(path, foreign)
    install.install_settings(root)

    _, changed = install.uninstall_settings(root)
    assert changed is True

    data = _read(path)
    stop_commands = _all_commands(data, "Stop")
    assert "python3 my_other_tool.py" in stop_commands
    assert not any("plateau hook" in c or "plateau.cli hook" in c for c in stop_commands)


def test_uninstall_drops_events_left_entirely_ours(root):
    path = _settings_path(root)
    install.install_settings(root)  # no foreign entries anywhere

    install.uninstall_settings(root)
    data = _read(path)
    # every event we installed was 100% ours -- nothing foreign to keep
    for event in ("SessionStart", "PostToolUse", "PreCompact", "Stop", "SessionEnd", "SubagentStop"):
        assert event not in data.get("hooks", {}) or _all_commands(data, event) == []


def test_uninstall_is_noop_when_nothing_installed(root):
    _, changed = install.uninstall_settings(root)
    assert changed is False
    assert not os.path.isfile(_settings_path(root))


def test_uninstall_is_noop_on_second_run(root):
    path = _settings_path(root)
    _write(path, {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 x.py", "timeout": 5}]}]}})
    install.install_settings(root)
    install.uninstall_settings(root)
    before = _read(path)
    _, changed = install.uninstall_settings(root)
    after = _read(path)
    assert changed is False
    assert before == after


# ---------------------------------------------------------------------------
# backup written once
# ---------------------------------------------------------------------------

def test_backup_written_once_on_first_real_change(root):
    path = _settings_path(root)
    original = {"foo": "bar"}
    _write(path, original)

    install.install_settings(root)
    backup_path = path + ".plateau.bak"
    assert os.path.isfile(backup_path)
    assert _read(backup_path) == original

    # further changes (e.g. an uninstall) must never overwrite the ORIGINAL backup
    install.uninstall_settings(root)
    assert _read(backup_path) == original


def test_no_backup_when_file_did_not_previously_exist(root):
    install.install_settings(root)
    assert not os.path.isfile(_settings_path(root) + ".plateau.bak")


def test_no_backup_on_a_true_noop_install(root):
    path = _settings_path(root)
    original = {"foo": "bar"}
    _write(path, original)

    install.install_settings(root)  # first real change -> backup made
    os.remove(path + ".plateau.bak")

    install.install_settings(root)  # second call: no change at all
    assert not os.path.isfile(path + ".plateau.bak")


# ---------------------------------------------------------------------------
# --global / bridge.toml copy (adjacent contract, still B4's file to cover)
# ---------------------------------------------------------------------------

def test_global_settings_path_is_under_home(root):
    path = install.settings_path(root, is_global=True)
    assert path == os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def test_copy_global_bridge_toml_does_not_overwrite_without_force(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    dest_dir = tmp_path / ".plateau"
    dest_dir.mkdir()
    dest = dest_dir / "bridge.toml"
    dest.write_text("version = \"custom\"\n")

    result = install.copy_global_bridge_toml(force=False)
    assert result == str(dest)
    assert dest.read_text() == "version = \"custom\"\n"

    install.copy_global_bridge_toml(force=True)
    assert dest.read_text() != "version = \"custom\"\n"
