"""config auto-detect + override + bootstrap tiering (web + source fallback + skipdirs)."""
import json

from plateau_qa import config, bootstrap


def _mkrepo(tmp_path, files):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return str(tmp_path)


def test_autodetect_gate_commands(tmp_path):
    repo = _mkrepo(tmp_path, {
        "package.json": json.dumps({"scripts": {"test": "jest", "build:ci": "vite build", "lint": "eslint ."}}),
        "jest.config.js": "module.exports={}",
    })
    cfg = config.load_config(repo)
    assert cfg["gate_commands"]["unit"][:2] == ["npx", "jest"]
    assert cfg["gate_commands"]["build"] == ["npm", "run", "build:ci"]
    assert cfg["gate_commands"]["lint"] == ["npm", "run", "lint"]


def test_autodetect_pytest_for_python_repo(tmp_path):
    repo = _mkrepo(tmp_path, {"pyproject.toml": "[project]\nname='x'\n", "mod.py": "x=1"})
    cfg = config.load_config(repo)
    assert cfg["gate_commands"]["unit"] == ["python", "-m", "pytest", "-q"]


def test_override_wins_defaults_preserved(tmp_path):
    repo = _mkrepo(tmp_path, {"package.json": "{}"})
    ov = tmp_path / "o.json"
    ov.write_text(json.dumps({"tiers": {"sec_pattern": "ONLYTHIS"}}))
    cfg = config.load_config(repo, str(ov))
    assert cfg["tiers"]["sec_pattern"] == "ONLYTHIS"
    assert "core_pattern" in cfg["tiers"]            # untouched default survives


def test_web_tiering(tmp_path):
    repo = _mkrepo(tmp_path, {
        "src/App.tsx": '<Route path="/admin/x" /><Route path="/about" /><Route path="/checkout" />',
        "supabase/functions/admin-withdraw/index.ts": "x",
        "supabase/functions/health/index.ts": "x",
        "supabase/migrations/1_x.sql": "CREATE POLICY p ON t USING (true);",
    })
    cov = bootstrap.build_coverage(repo, config.load_config(repo))
    byid = {e["id"]: e for e in cov}
    assert byid["policy:1_x.sql"]["tier"] == 1
    assert byid["edge_fn:admin-withdraw"]["tier"] == 1   # matches default sec keywords
    assert byid["edge_fn:health"]["tier"] == 4       # unlisted -> hardening, not SEC
    assert byid["page:/admin/x"]["tier"] == 1
    assert byid["page:/checkout"]["tier"] == 2
    assert byid["page:/about"]["tier"] == 3


def test_source_fallback_and_skipdirs(tmp_path):
    repo = _mkrepo(tmp_path, {
        "auth_handler.py": "x",                       # sec keyword -> tier 1
        "util.py": "x",                               # tier 3
        ".venv/lib/python3.9/site-packages/junk.py": "x",
        "node_modules/dep/m.py": "x",
    })
    cov = bootstrap.build_coverage(repo, config.load_config(repo))  # no router/supabase -> source
    byid = {e["id"]: e for e in cov}
    assert all(e["kind"] == "module" for e in cov)
    assert "module:auth_handler.py" in byid and byid["module:auth_handler.py"]["tier"] == 1
    assert "module:util.py" in byid
    assert not any(".venv" in i or "site-packages" in i or "node_modules" in i for i in byid)
