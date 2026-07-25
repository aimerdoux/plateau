"""Free mock-verification of the D-036 harness — a PREREG guard ("Mock-plumb the
harness free ... BEFORE any run"). No LLM, no long evolution: pure correctness
checks on the integrator, seeder, detector, and the seal round-trip.

Run:  python mock_verify.py     (exits 0 on all-pass)
"""
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np

from cgle import CGLE

FAILS = []


def check(name, cond, detail=""):
    ok = bool(cond)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def test_detector_known_configs():
    """A single +/- pair must read exactly 2 defects with the right charges and
    positions; the detector must be sign-correct."""
    s = CGLE(b=0.5, c=-0.6, N=128, side=64.0, dt=0.05, seed=0)
    s.seed_vortices([(24.0, 32.0), (40.0, 32.0)], [+1, -1])
    pos, ch = s.find_defects()
    check("single pair -> 2 defects", len(ch) == 2, f"got {len(ch)}")
    check("pair is charge-neutral", int(np.sum(ch)) == 0, f"sum={int(np.sum(ch))}")
    check("both unit charges", sorted(ch.tolist()) == [-1, 1], f"{sorted(ch.tolist())}")
    # nearest detected defect to each seeded centre is within one grid cell
    if len(ch) == 2:
        d0 = np.min(np.linalg.norm(pos - np.array([24.0, 32.0]), axis=1))
        d1 = np.min(np.linalg.norm(pos - np.array([40.0, 32.0]), axis=1))
        check("defects localize to seeds", d0 < 1.5 and d1 < 1.5,
              f"d0={d0:.2f} d1={d1:.2f} (dx={s.dx})")


def test_seeder_neutrality_guard():
    s = CGLE(b=0.5, c=-0.6, N=64, side=32.0, dt=0.05, seed=0)
    raised = False
    try:
        s.seed_vortices([(8, 8), (16, 16)], [+1, +1])  # net charge +2
    except ValueError:
        raised = True
    check("non-neutral seed rejected", raised)


def test_seeder_periodic_no_seam():
    """A pair near the box edge must not nucleate spurious seam defects (the whole
    reason for the periodic image sum)."""
    s = CGLE(b=0.5, c=-0.6, N=256, side=128.0, dt=0.05, seed=0)
    s.seed_vortices([(4.0, 64.0), (124.0, 64.0)], [+1, -1])  # both hug the seam
    pos, ch = s.find_defects()
    check("edge pair -> exactly 2 defects (no seam)", len(ch) == 2, f"got {len(ch)}")


def test_etd2_uniform_rotation():
    """Exact CGLE check: the uniform state |A|=1 obeys dA/dt=-i c A (it rotates at
    rate -c with |A| conserved). Because the scheme carries +A linearly and cancels
    it against the nonlinear -(1+ic)|A|^2 A, the residual is pure ETD2 truncation
    error. Validate it is (a) small and (b) genuinely 2nd order: halving dt over the
    same physical time must cut the error ~4x. That is threshold-free and catches a
    wrong scheme far better than a magic tolerance."""
    c = -0.6
    T_phys = 10.0

    def run(dt):
        n = int(round(T_phys / dt))
        s = CGLE(b=0.5, c=c, N=32, side=16.0, dt=dt, seed=0)
        s.A = np.ones((32, 32), dtype=complex)
        s._Nprev_hat = None
        s.evolve(n)
        t = n * dt
        amp_err = float(np.max(np.abs(np.abs(s.A) - 1.0)))
        phase = float(np.angle(s.A[0, 0]))
        expected = ((-c * t + np.pi) % (2 * np.pi)) - np.pi
        phase_err = abs(((phase - expected + np.pi) % (2 * np.pi)) - np.pi)
        return amp_err, phase_err

    a1, p1 = run(0.05)
    a2, p2 = run(0.025)
    check("uniform |A| error small", a1 < 1e-3, f"amp_err(dt=.05)={a1:.2e}")
    check("uniform phase error small", p1 < 5e-3, f"phase_err(dt=.05)={p1:.2e}")
    ratio_a = a1 / max(a2, 1e-15)
    ratio_p = p1 / max(p2, 1e-15)
    check("|A| error is ~2nd order (ratio~4)", 3.0 < ratio_a < 5.0, f"ratio={ratio_a:.2f}")
    check("phase error is ~2nd order (ratio~4)", 3.0 < ratio_p < 5.0, f"ratio={ratio_p:.2f}")


def test_etd2_bounded_random():
    """A random small-amplitude init must stay bounded (no blow-up) — a stability
    sanity check on the scheme, not a physics claim."""
    s = CGLE(b=0.5, c=-0.6, N=64, side=32.0, dt=0.05, seed=3)
    rng = np.random.default_rng(3)
    s.A = 0.1 * (rng.standard_normal((64, 64)) + 1j * rng.standard_normal((64, 64)))
    s._Nprev_hat = None
    s.evolve(500)
    amax = float(np.abs(s.A).max())
    check("random init stays bounded", np.isfinite(amax) and amax < 3.0, f"|A|max={amax:.2f}")


def test_seal_roundtrip():
    """The integrity seal-before-score round trip: write a raw file, seal it,
    verify the chain and files, and confirm a tamper is caught."""
    from plateau.integrity import Manifest, seal, is_sealed
    with tempfile.TemporaryDirectory() as root:
        man = Manifest(os.path.join(root, "manifest.jsonl"))
        p = os.path.join(root, "datum.json")
        with open(p, "w") as fh:
            fh.write('{"defects": 26, "frozen": true}')
        seal(p, man, root=root, kind="raw")
        check("file is sealed (read-only)", is_sealed(p))
        ok_chain, _ = man.verify_chain()
        ok_files, bad = man.verify_files(root)
        check("manifest chain verifies", ok_chain)
        check("sealed files verify", ok_files, f"bad={bad}")
        # tamper: force-write and confirm detection
        os.chmod(p, 0o644)
        with open(p, "w") as fh:
            fh.write('{"defects": 999, "frozen": false}')
        ok_files2, bad2 = man.verify_files(root)
        check("tamper is detected", not ok_files2, f"bad={bad2}")


def main():
    print("D-036 harness mock-verify (free; no LLM, no long run)\n")
    for t in (test_detector_known_configs, test_seeder_neutrality_guard,
              test_seeder_periodic_no_seam, test_etd2_uniform_rotation,
              test_etd2_bounded_random, test_seal_roundtrip):
        print(t.__name__ + ":")
        t()
    print()
    if FAILS:
        print(f"MOCK-VERIFY FAILED: {FAILS}")
        sys.exit(1)
    print("MOCK-VERIFY PASSED — harness is free-verified; scored runs may proceed.")


if __name__ == "__main__":
    main()
