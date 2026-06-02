"""Optional integrity layer: write-once seal + tamper-evident manifest. The core does
not require this; these tests pin it for when you do turn it on."""

from __future__ import annotations

import os

import pytest

from plateau.integrity import seal, Manifest, file_hash, is_sealed


def test_seal_is_write_once(tmp_path):
    p = tmp_path / "raw.json"; p.write_text('{"a":1}')
    m = Manifest(str(tmp_path / "manifest.jsonl"))
    seal(str(p), m, str(tmp_path), kind="raw")
    assert is_sealed(str(p))
    with pytest.raises(PermissionError):
        seal(str(p), m, str(tmp_path), kind="raw")  # refuses re-seal


def test_manifest_verifies_clean(tmp_path):
    p = tmp_path / "raw.json"; p.write_text('{"a":1}')
    m = Manifest(str(tmp_path / "manifest.jsonl"))
    seal(str(p), m, str(tmp_path), kind="raw")
    okc, ec = m.verify_chain()
    okf, ef = m.verify_files(str(tmp_path))
    assert okc and okf, (ec, ef)


def test_tamper_is_detected(tmp_path):
    p = tmp_path / "raw.json"; p.write_text('{"a":1}')
    m = Manifest(str(tmp_path / "manifest.jsonl"))
    seal(str(p), m, str(tmp_path), kind="raw")
    os.chmod(str(p), 0o644)
    p.write_text('{"a":2}')  # the exact move the c4 tamper drill made
    okf, ef = m.verify_files(str(tmp_path))
    assert okf is False
    assert any("TAMPER" in e for e in ef)


def test_manifest_chain_detects_truncation(tmp_path):
    mp = tmp_path / "manifest.jsonl"
    a = tmp_path / "a.txt"; a.write_text("a")
    b = tmp_path / "b.txt"; b.write_text("b")
    m = Manifest(str(mp))
    seal(str(a), m, str(tmp_path)); seal(str(b), m, str(tmp_path))
    okc, _ = m.verify_chain()
    assert okc
    # rewrite history: drop the first line → chain break on the survivor
    lines = mp.read_text().splitlines()
    mp.write_text(lines[1] + "\n")
    okc2, ec2 = m.verify_chain()
    assert okc2 is False and ec2
