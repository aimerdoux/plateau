"""Suite-wide isolation: every test sees an empty HOME.

config.load merges ~/.plateau/bridge.toml and the pressure/doctor code reads
~/.claude/settings.json; a real override on the developer's machine (a raised
`[lab] holdout_rate` for a measurement window, 2026-09-22) otherwise leaks into the
suite and fails tests that expect the packaged defaults. Subprocess hooks inherit it.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", raising=False)
    yield home
