"""Context-slope decision rule + bounded-context early warning. These pin the
INSTRUMENT so a real run's verdict is computed, never declared."""

from __future__ import annotations

from plateau.metrics import ArmCurve, decide, control_leaks, early_warning, slope


def _climbing_control():
    return ArmCurve("control", list(range(6)),
                    [3000, 8000, 13000, 18000, 23000, 28000], [1] * 6)


def _flat_plateau(completions=None):
    return ArmCurve("plateau", list(range(6)),
                    [1200, 1250, 1230, 1280, 1260, 1270], completions or [1] * 6)


def test_slope_basic():
    assert slope([0, 1, 2, 3], [0, 2, 4, 6]) == 2.0
    assert slope([0, 1, 2], [5, 5, 5]) == 0.0


def test_win_when_flat_at_parity():
    d = decide(_climbing_control(), _flat_plateau())
    assert d["claims"]["context_flattened_<=25%_control"] is True
    assert d["claims"]["completion_parity"] is True
    assert d["verdict"].startswith("WIN")


def test_partial_when_flat_but_forgets():
    d = decide(_climbing_control(), _flat_plateau([1, 0, 0, 0, 1, 0]))
    assert d["claims"]["context_flattened_<=25%_control"] is True
    assert d["claims"]["completion_parity"] is False
    assert d["verdict"].startswith("PARTIAL")


def test_null_when_plateau_also_climbs():
    climber = ArmCurve("plateau", list(range(6)),
                       [3000, 7800, 12500, 17200, 22000, 26500], [1] * 6)
    d = decide(_climbing_control(), climber)
    assert d["claims"]["context_flattened_<=25%_control"] is False
    assert d["verdict"].startswith("NULL")


def test_unscorable_when_control_flat():
    flat_ctrl = ArmCurve("control", list(range(6)), [3000] * 6, [1] * 6)
    d = decide(flat_ctrl, _flat_plateau())
    assert d["claims"]["anti_rig_control_climbs"] is False
    assert d["verdict"].startswith("UNSCORABLE")


def test_control_leaks_gate():
    assert control_leaks(_climbing_control().finalize()) is True
    assert control_leaks(ArmCurve("c", list(range(3)), [100, 100, 100], [1, 1, 1]).finalize()) is False


def test_early_warning_predicts_breach():
    w = early_warning([3000, 8000, 13000, 18000], budget=50000)
    assert w["will_breach"] is True
    assert w["steps_to_breach"] is not None and w["steps_to_breach"] > 0


def test_early_warning_flat_never_breaches():
    # genuinely flat (zero/neg slope) → bounded, never breaches. A slightly-positive
    # series WOULD breach eventually, and the metric honestly reports that.
    w = early_warning([1250, 1250, 1250, 1250], budget=50000)
    assert w["will_breach"] is False
    assert w["steps_to_breach"] is None


def test_mock_plumbing_fires_all_branches():
    from plateau.metrics import run_mock_plumbing
    out = run_mock_plumbing()
    assert out["WIN_shape"]["verdict"].startswith("WIN")
    assert out["PARTIAL_shape"]["verdict"].startswith("PARTIAL")
    assert out["UNSCORABLE_shape"]["verdict"].startswith("UNSCORABLE")
