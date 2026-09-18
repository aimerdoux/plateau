"""tests/test_ring.py — owner C5 (docs/harness-0.3/PLAN-step4.md "Tests (C5)").

Per the plan's "Tests (C5)" line: "sync off without key; path remote round-trip; curate
promotes a 3x shape and demotes an unused entry." Every git operation here targets a
disposable path remote (a local `git init --bare` directory) -- no network, matching
PLAN-step4.md "Private ring": "Path-based remotes work without network (tests use a temp
dir remote)." `HOME` is isolated to a directory under `tmp_path` for every test that
actually runs `sync()`, so this suite never reads or writes the real developer's
`~/.plateau/ring/`.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess

from plateau import ring as ring_mod
from plateau.bridge import common as bridge_common
from plateau.lab import ledger as ledger_mod


def _write_config(root, remote="", key=""):
    pd = os.path.join(root, ".plateau")
    os.makedirs(pd, exist_ok=True)
    with open(os.path.join(pd, "config.toml"), "w", encoding="utf-8") as f:
        f.write('[private_ring]\nremote = "{}"\nkey = "{}"\n'.format(remote, key))


# ---------------------------------------------------------------------------
# sync off without key (or without remote, or with the key's env var unset)
# ---------------------------------------------------------------------------


def test_sync_off_with_no_config_at_all(tmp_path):
    assert ring_mod.sync(str(tmp_path)) == "private ring: off"
    assert ring_mod.status(str(tmp_path)) == "off (no remote configured)"


def test_sync_off_without_a_key_name(tmp_path):
    root = str(tmp_path)
    _write_config(root, remote="/some/path", key="")
    assert ring_mod.sync(root) == "private ring: off"
    assert ring_mod.status(root) == "off (no key configured)"


def test_sync_off_when_the_named_env_var_is_unset(tmp_path, monkeypatch):
    root = str(tmp_path)
    _write_config(root, remote="/some/path", key="PLATEAU_RING_TEST_TOKEN_UNSET")
    monkeypatch.delenv("PLATEAU_RING_TEST_TOKEN_UNSET", raising=False)
    assert ring_mod.sync(root) == "private ring: off"
    assert ring_mod.status(root) == "off (env PLATEAU_RING_TEST_TOKEN_UNSET not set)"


def test_status_on_when_remote_key_and_env_all_set(tmp_path, monkeypatch):
    root = str(tmp_path)
    _write_config(root, remote="/some/path", key="PLATEAU_RING_TEST_TOKEN_SET")
    monkeypatch.setenv("PLATEAU_RING_TEST_TOKEN_SET", "dummy")
    assert ring_mod.status(root).startswith("on ")


# ---------------------------------------------------------------------------
# path remote round-trip (no network)
# ---------------------------------------------------------------------------


def test_sync_path_remote_round_trip(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PLATEAU_RING_TEST_TOKEN", "dummy-token-value")

    bare_remote = str(tmp_path / "bare_remote.git")
    subprocess.run(["git", "init", "--quiet", "--bare", bare_remote], check=True, capture_output=True)

    root = str(tmp_path / "proj")
    _write_config(root, remote=bare_remote, key="PLATEAU_RING_TEST_TOKEN")

    lconn = ledger_mod.db(root)
    lconn.execute("INSERT INTO sessions(session_id, agent_id, agent) VALUES('s1', '', 'main')")
    lconn.commit()
    lconn.close()

    status1 = ring_mod.sync(root)
    assert status1.startswith("private ring: synced")

    ledger_path = os.path.join(root, ".plateau", "ledger.sqlite")
    assert os.path.isfile(ledger_path)

    # simulate a fresh checkout of the same project (ledger lost locally) -- sync
    # again and it must come back down from the ring remote.
    os.remove(ledger_path)
    assert not os.path.isfile(ledger_path)

    status2 = ring_mod.sync(root)
    assert status2.startswith("private ring: synced")
    assert os.path.isfile(ledger_path)

    conn2 = sqlite3.connect(ledger_path)
    try:
        got = conn2.execute("SELECT session_id, agent FROM sessions").fetchall()
    finally:
        conn2.close()
    assert got == [("s1", "main")]


def test_sync_isolates_two_projects_sharing_one_remote(tmp_path, monkeypatch):
    """Different projects (different `repo_key()`s) publishing to the SAME ring remote
    land in separate subdirectories and never see each other's ledger."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PLATEAU_RING_TEST_TOKEN", "dummy-token-value")

    bare_remote = str(tmp_path / "bare_remote.git")
    subprocess.run(["git", "init", "--quiet", "--bare", bare_remote], check=True, capture_output=True)

    root_a = str(tmp_path / "proj_a")
    root_b = str(tmp_path / "proj_b")
    _write_config(root_a, remote=bare_remote, key="PLATEAU_RING_TEST_TOKEN")
    _write_config(root_b, remote=bare_remote, key="PLATEAU_RING_TEST_TOKEN")

    lconn = ledger_mod.db(root_a)
    lconn.execute("INSERT INTO sessions(session_id, agent_id, agent) VALUES('a-only', '', 'main')")
    lconn.commit()
    lconn.close()

    assert ring_mod.repo_key(root_a) != ring_mod.repo_key(root_b)

    ring_mod.sync(root_a)
    ring_mod.sync(root_b)

    assert not os.path.isfile(os.path.join(root_b, ".plateau", "ledger.sqlite"))


# ---------------------------------------------------------------------------
# curate(): promotes a 3x-repeated shape, demotes an unused entry
# ---------------------------------------------------------------------------


def test_curate_promotes_repeated_shape_and_demotes_unused_file(tmp_path):
    root = str(tmp_path)
    store_conn = bridge_common.db(root)
    for i in range(3):
        store_conn.execute(
            "INSERT INTO receipts(ts, session_id, agent, tool, target, kind, outcome, detail) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (1000.0 + i, "s1", "main", "Bash", "pytest -q", "test", "pass", ""),
        )
    store_conn.commit()

    curated_conn = ring_mod.curated_db(os.path.join(root, ".plateau", "curated.sqlite"))
    try:
        ring_mod.curate(store_conn, curated_conn)  # session_count -> 1

        proc = curated_conn.execute(
            "SELECT uses FROM procedures WHERE name=?", ("Bash:test:pass",),
        ).fetchone()
        assert proc is not None, "a (tool,kind,outcome) shape seen 3x must be promoted"
        assert proc[0] == 1

        # below the 3x threshold: a shape seen only twice is never promoted
        store_conn.execute(
            "INSERT INTO receipts(ts, session_id, agent, tool, target, kind, outcome, detail) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (2000.0, "s1", "main", "Bash", "echo hi", "command", "pass", ""),
        )
        store_conn.execute(
            "INSERT INTO receipts(ts, session_id, agent, tool, target, kind, outcome, detail) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (2001.0, "s1", "main", "Bash", "echo bye", "command", "pass", ""),
        )
        store_conn.commit()
        ring_mod.curate(store_conn, curated_conn)  # session_count -> 2
        assert curated_conn.execute(
            "SELECT 1 FROM procedures WHERE name=?", ("Bash:command:pass",),
        ).fetchone() is None

        # seed one stale `files` row directly (never touched by `_curate_files`, since
        # its path never appears as a `nodes` row in `store_conn`) at uses==0,
        # last_used==1 (the first curate() tick above).
        curated_conn.execute(
            "INSERT INTO files(path, role, uses, last_used) VALUES(?,?,?,?)",
            ("stale/unused.py", "file", 0, 1),
        )
        curated_conn.commit()

        for _ in range(9):  # session_count -> 3..11
            ring_mod.curate(store_conn, curated_conn)

        row = curated_conn.execute(
            "SELECT 1 FROM files WHERE path=?", ("stale/unused.py",),
        ).fetchone()
        assert row is None, "a files row at uses==0 for >= 10 curate() ticks must be demoted"
    finally:
        store_conn.close()
        curated_conn.close()


def test_curate_bumps_uses_for_a_touched_file(tmp_path):
    root = str(tmp_path)
    store_conn = bridge_common.db(root)
    store_conn.execute(
        "INSERT INTO nodes(key, kind, first_rid, last_rid, degree, last_outcome, "
        "last_detail, session_id, agent) VALUES(?,?,?,?,?,?,?,?,?)",
        ("plateau/bridge/query.py", "file", 1, 1, 1, "read", "", "s1", "main"),
    )
    store_conn.commit()

    curated_conn = ring_mod.curated_db(os.path.join(root, ".plateau", "curated.sqlite"))
    try:
        ring_mod.curate(store_conn, curated_conn)
        ring_mod.curate(store_conn, curated_conn)

        row = curated_conn.execute(
            "SELECT uses, last_used FROM files WHERE path=?", ("plateau/bridge/query.py",),
        ).fetchone()
        assert row == (2, 2)  # touched on both ticks -> never demoted, uses grows
    finally:
        store_conn.close()
        curated_conn.close()
