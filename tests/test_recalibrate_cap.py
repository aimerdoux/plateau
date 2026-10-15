"""RECALIBRATE.md is append-only across a run (see test_adapt.py's
test_recalibration_file_records_only_actionable_gaps). Left unchecked that means a long
autoloop grows the file without bound. `adapt._cap_recalibration`, called at the end of
`write_recalibration`, rolls the OLDEST recalibration blocks off once a byte cap is hit — these
tests fail if that rollover is removed or broken.
"""
from plateau.agency import adapt as A


def _gap(i):
    return A.Gap(task=f"T{i}", klass=A.DRIFT,
                 predicted=f"predicted-{i}" * 5, observed=f"observed-{i}" * 5)


def test_recalibrate_file_never_exceeds_its_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "_RECALIBRATE_MAX_BYTES", 2000)
    for i in range(50):
        A.write_recalibration(str(tmp_path), [_gap(i)], note=f"round {i}")
    size = (tmp_path / "RECALIBRATE.md").stat().st_size
    # Each round is ~300+ bytes; 50 uncapped rounds would be well over 10x the cap. Bounded to
    # a small multiple of the cap proves rollover fired repeatedly, not just once.
    assert size <= 2000 * 2


def test_recalibrate_cap_rolls_oldest_blocks_first(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "_RECALIBRATE_MAX_BYTES", 2000)
    for i in range(50):
        A.write_recalibration(str(tmp_path), [_gap(i)], note=f"round {i}")
    body = (tmp_path / "RECALIBRATE.md").read_text()
    assert "round 49" in body            # most recent survives
    assert "round 0" not in body         # oldest rolled off
    assert body.startswith("# RECALIBRATE")   # title line always kept


def test_recalibrate_cap_is_a_noop_under_the_bound(tmp_path):
    """Under the cap nothing rolls off: the note and the entry both survive verbatim.

    NOTE: as first written this asserted `"round 1" in body` while passing
    `note="only round"` — a string that is never written. Sixteen consecutive workers tried
    to satisfy it by changing the IMPLEMENTATION; the gate itself was wrong. Fixed to assert
    what the test name says it checks.
    """
    path = A.write_recalibration(str(tmp_path), [_gap(1)], note="only round")
    body = open(path).read()
    assert "only round" in body          # the note that was actually passed
    assert "**T1 [" in body              # and the entry itself survived
    assert body.startswith("# RECALIBRATE")


def test_recalibrate_cap_leaves_a_single_oversized_block_intact(tmp_path, monkeypatch):
    # A cap so small that even ONE block blows past it: there is nothing older to roll, so the
    # block must survive whole rather than being truncated mid-entry.
    monkeypatch.setattr(A, "_RECALIBRATE_MAX_BYTES", 10)
    huge = A.Gap(task="T1", klass=A.REFUTED, predicted="p" * 500, observed="o" * 500,
                 blocker="EXTERNAL", unblock="retry with backoff")
    path = A.write_recalibration(str(tmp_path), [huge])
    body = open(path).read()
    assert "**T1 [" in body
    assert "p" * 500 in body
