"""Σ operator slice — acceptance tests A1, A2, A3 (SPEC §7, §10).

Anchored to a REAL logged Plateau deliverable: `demo/verdict6b.json` — the sealed demo6b
2-arm efficiency verdict (efficiency.verdict == "WIN", harness4_pin_ok, completion_parity).
Its sibling sealed manifest `demo/raw6b/manifest.jsonl` is a second real on-disk referent.
`external_anchor` binds the verdict's content hash + path, resolving OUTSIDE the loop.

τ (pre-registered, A1): τ = 1.0.
  Rationale — the anchor's gates are DECIDABLE KPIs of a sealed verdict (a boolean WIN, a
  boolean pin, a boolean parity). Partial credit on "is this verdict a WIN" is meaningless, so
  the round-trip bar is full pass (all gates at threshold). The soft `feasibility` number still
  forms a monotone ladder across iterations as the deterministic generator pays depth toward the
  complete candidate — that ladder is what proves the loop compounds (A1 also asserts it climbs).
"""

from __future__ import annotations

import json
import os

import pytest

from plateau.sigma import (
    FossilStore,
    Gate,
    Intent,
    LoopConfig,
    Schema,
    Verifier,
    evaluate,
    extract_schema,
    register_check,
    run_schema,
)

# ---- locate the real anchor deliverable relative to the repo root -------------
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ANCHOR_VERDICT = os.path.join(_REPO_ROOT, "demo", "verdict6b.json")
ANCHOR_MANIFEST = os.path.join(_REPO_ROOT, "demo", "raw6b", "manifest.jsonl")

TAU = 1.0  # pre-registered round-trip threshold (see module docstring)


# ---- programmatic checkers reading the REAL deliverable on disk ---------------
# Registered once at import; checkers read the anchor verdict's actual bytes, so the gate
# certifies the real KPI, not a candidate's self-claim.

@register_check("verdict6b_is_win")
def _check_win(candidate, gate):
    with open(ANCHOR_VERDICT, encoding="utf-8") as f:
        v = json.load(f)
    produced = candidate.get("efficiency_verdict") if isinstance(candidate, dict) else None
    # gate passes only if the candidate reproduces the deliverable's real verdict.
    return 1.0 if produced == v["efficiency"]["verdict"] else 0.0


@register_check("verdict6b_pin_ok")
def _check_pin(candidate, gate):
    with open(ANCHOR_VERDICT, encoding="utf-8") as f:
        v = json.load(f)
    produced = candidate.get("harness4_pin_ok") if isinstance(candidate, dict) else None
    return 1.0 if produced == v["harness4_pin_ok"] else 0.0


@register_check("verdict6b_parity")
def _check_parity(candidate, gate):
    with open(ANCHOR_VERDICT, encoding="utf-8") as f:
        v = json.load(f)
    produced = candidate.get("completion_parity") if isinstance(candidate, dict) else None
    return 1.0 if produced == v["efficiency"]["completion_parity"] else 0.0


def _anchor_session_and_deliverable():
    """The session record + deliverable spec extract_schema inverts. Gates carry the real
    KPIs of D; the test-kind gate hash-pins the sealed manifest as an external referent."""
    from plateau.integrity import file_hash
    manifest_hash = file_hash(ANCHOR_MANIFEST)
    session = {"session_hash": "sha256:demo6b-session", "turns": 6}
    deliverable = {
        "path": ANCHOR_VERDICT,
        "max_iterations": 6,
        "stop_rule": "either",
        "gates": [
            {"id": "g_win", "kpi": "efficiency.verdict == WIN", "kind": "programmatic",
             "check": "verdict6b_is_win", "threshold": 1.0, "weight": 2.0},
            {"id": "g_pin", "kpi": "harness4_pin_ok", "kind": "programmatic",
             "check": "verdict6b_pin_ok", "threshold": 1.0, "weight": 1.0},
            {"id": "g_parity", "kpi": "completion_parity", "kind": "programmatic",
             "check": "verdict6b_parity", "threshold": 1.0, "weight": 1.0},
            # test-kind gate: the sealed manifest must still hash to its recorded value.
            {"id": "g_manifest", "kpi": "sealed manifest integrity", "kind": "test",
             "check": f"{ANCHOR_MANIFEST}@{manifest_hash}", "threshold": 1.0, "weight": 1.0},
        ],
    }
    clean_intent = {
        "goal": "Reproduce the demo6b efficiency verdict (2-arm WIN, pin ok, parity held)",
        "target_invariants": ["efficiency.verdict == WIN", "harness4_pin_ok", "completion_parity"],
        "constraints": ["must reproduce the sealed verdict's KPIs exactly"],
        "excluded_paths": ["single-arm autonomy claim (demo4 NULL stands)"],
    }
    return session, deliverable, clean_intent


def _deterministic_generator():
    """An injected deterministic model `(intent, context, iteration) -> candidate` (no LLM).

    Crucially STATEFUL via Φ: it reads `context["best_feasibility"]` (hydrated from the
    persisted loop-state) and pays one more KPI of depth per rung — so depth COMPOUNDS across
    iterations instead of re-rolling the same shallow candidate (§9.1). By the final rung it
    emits the full correct candidate that reproduces the real verdict."""
    truth = json.load(open(ANCHOR_VERDICT, encoding="utf-8"))
    win = truth["efficiency"]["verdict"]
    pin = truth["harness4_pin_ok"]
    parity = truth["efficiency"]["completion_parity"]
    # progressive disclosure keyed on how much depth has already been paid (hydrated context).
    rungs = [
        {},
        {"efficiency_verdict": win},
        {"efficiency_verdict": win, "harness4_pin_ok": pin},
        {"efficiency_verdict": win, "harness4_pin_ok": pin, "completion_parity": parity},
    ]

    def model(intent, context, iteration):
        # depth already paid (hydrated from Φ) selects how complete the candidate is.
        paid = len(context.get("paid_depth", []))
        rung = min(paid + 1, len(rungs) - 1)
        cand = dict(rungs[rung])
        # the test-kind gate keys on gate.id -> {artifact, hash}; pin the real manifest hash.
        if rung >= 1:
            from plateau.integrity import file_hash
            cand["g_manifest"] = {"artifact": ANCHOR_MANIFEST, "hash": file_hash(ANCHOR_MANIFEST)}
        return cand

    return model


# ============================== A1 — round-trip ================================

def test_A1_roundtrip_extract_then_run_passes_all_gates(tmp_path):
    """A1: extract_schema on the anchor → run_schema (deterministic generator) passes all
    gates ≥ τ. Also asserts the feasibility ladder is monotone-non-decreasing (depth compounds)."""
    session, deliverable, clean_intent = _anchor_session_and_deliverable()
    schema = extract_schema(session, deliverable, clean_intent)
    store = FossilStore(str(tmp_path / "phi"))

    result = run_schema(schema, _deterministic_generator(), store)

    assert result.all_pass, f"gates not all passing; failing={result.results.failing()}"
    assert result.feasibility >= TAU, f"feasibility {result.feasibility} < τ={TAU}"
    assert result.stop_reason == "all_gates_pass"
    # depth compounds: the soft feasibility ladder never goes DOWN across iterations.
    trace = result.feasibility_trace
    assert all(b >= a - 1e-9 for a, b in zip(trace, trace[1:])), \
        f"feasibility ladder not monotone (stateless re-roll?): {trace}"
    # Φ actually accumulated paid depth.
    assert result.fossils_written, "no fossils written — loop did not pay depth into Φ"


def test_A1_external_anchor_binds_real_deliverable():
    """The schema's V is anchored to the REAL on-disk verdict (hash@path), resolving outside
    the loop. An empty/unresolvable anchor is rejected at construction (§3.4)."""
    session, deliverable, clean_intent = _anchor_session_and_deliverable()
    schema = extract_schema(session, deliverable, clean_intent)
    assert ANCHOR_VERDICT in schema.verifier.external_anchor
    assert schema.verifier.external_anchor.startswith("sha256:")


# ============================== A2 — V immutability ============================

def test_A2_frozen_hash_constant_over_simulated_refine():
    """A2: over N simulated refine() steps, frozen_hash is CONSTANT.

    refine() (𝒮) is deferred (§10), so we SIMULATE it: produce N new Schemas that rewrite ι, Φ,
    γ (everything 𝒮 is allowed to touch) while carrying V across unchanged, and assert
    frozen_hash never moves. The refine-guard on the constitution certifies each step."""
    session, deliverable, clean_intent = _anchor_session_and_deliverable()
    original = extract_schema(session, deliverable, clean_intent)
    h0 = original.verifier.frozen_hash

    current = original
    N = 12
    for n in range(N):
        # a legal 𝒮 step: rewrite ι / γ / Φ, carry the SAME Verifier object (V untouched).
        new_intent = Intent(
            goal=current.intent.goal + f" (refined {n})",
            target_invariants=current.intent.target_invariants,
            constraints=current.intent.constraints,
            excluded_paths=current.intent.excluded_paths + (f"dead-end-{n}",),
            source_session_hash=current.intent.source_session_hash,
        )
        new_loop = LoopConfig(
            generator_policy=current.loop.generator_policy,
            max_iterations=current.loop.max_iterations + n,
            stop_rule=current.loop.stop_rule,
            state_handle=current.loop.state_handle,
            fossil_write=current.loop.fossil_write,
        )
        refined = Schema(intent=new_intent, verifier=current.verifier,
                         loop=new_loop, phi=current.phi)
        refined.assert_v_unchanged(original)          # the refine-guard certifies §3
        assert refined.verifier.frozen_hash == h0, "INVARIANT VIOLATION: V mutated"
        current = refined

    assert current.verifier.frozen_hash == h0


def test_A2_mutation_attempt_fails():
    """A2: a direct attempt to mutate V raises (frozen) — V cannot change in-session."""
    session, deliverable, clean_intent = _anchor_session_and_deliverable()
    schema = extract_schema(session, deliverable, clean_intent)
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        schema.verifier.external_anchor = "sha256:forged"   # frozen → rejected
    with pytest.raises(FrozenInstanceError):
        schema.verifier.frozen_hash = "sha256:forged"


def test_A2_refine_guard_catches_swapped_V():
    """A2: if a (buggy/malicious) refine swaps in a DIFFERENT V, the refine-guard fails loud."""
    session, deliverable, clean_intent = _anchor_session_and_deliverable()
    original = extract_schema(session, deliverable, clean_intent)
    # build a genuinely different V (a different gate set ⇒ different frozen_hash).
    other_v = Verifier(
        gates=(Gate(id="x", kpi="other", kind="programmatic", check="verdict6b_is_win"),),
        external_anchor=original.verifier.external_anchor,
    )
    assert other_v.frozen_hash != original.verifier.frozen_hash
    bad = Schema(intent=original.intent, verifier=other_v, loop=original.loop)
    with pytest.raises(ValueError, match="INVARIANT VIOLATION"):
        bad.assert_v_unchanged(original)


def test_A2_empty_anchor_rejected_at_construction():
    """§3.4: a verifier with no resolvable external anchor is rejected at construction."""
    g = (Gate(id="g", kpi="k", kind="programmatic", check="verdict6b_is_win"),)
    with pytest.raises(ValueError, match="external_anchor"):
        Verifier(gates=g, external_anchor="")
    with pytest.raises(ValueError, match="external_anchor"):
        Verifier(gates=g, external_anchor="not-a-hash-and-not-a-path")


# ============================== A3 — fossil dedup =============================

def test_A3_two_sessions_same_depth_dedup(tmp_path):
    """A3: two 'sessions' paying the SAME depth → hash collision; reuse_report shows the
    second reusing the first (cross-session dedup is the headline, §5)."""
    store = FossilStore(str(tmp_path / "phi"))          # shared substrate across sessions
    artifact = b"expensive-paid-depth: the same residue both sessions derive"

    # session A pays the depth
    h_a = store.put(artifact, provenance={"session": "A", "turn": 3, "cost": 1.0})
    # session B independently pays the SAME depth
    h_b = store.put(artifact, provenance={"session": "B", "turn": 5, "cost": 1.0})

    assert h_a == h_b, "same depth must land on the same content address"
    rep = store.reuse_report()
    assert rep.puts == 2
    assert rep.unique == 1, "only one unique fossil should be stored"
    assert rep.reused == 1, "the second session must be recorded as a reuse"
    assert h_a in rep.reused_hashes
    # and the fossil round-trips with integrity intact.
    assert store.get(h_a) == artifact


def test_A3_get_integrity_failure_is_hard_error(tmp_path):
    """§5: get() is integrity-checked — corrupting a stored blob is a HARD ERROR, never a
    silent return."""
    store = FossilStore(str(tmp_path / "phi"))
    h = store.put("payload", provenance={"session": "A", "turn": 0})
    # corrupt the stored blob behind the store's back.
    blob = store._blob_path(h)
    with open(blob, "wb") as f:
        f.write(b"tampered")
    with pytest.raises(ValueError, match="INTEGRITY FAILURE"):
        store.get(h)


def test_A3_provenance_mandatory_on_write(tmp_path):
    """§5: provenance is mandatory on write."""
    store = FossilStore(str(tmp_path / "phi"))
    with pytest.raises(ValueError, match="provenance"):
        store.put("x", provenance={})


# ============================== guards ========================================

def test_llm_judge_gate_is_deferred_loudly():
    """§10: llm_judge gates are deferred — evaluate() raises rather than silently passing."""
    v = Verifier(
        gates=(Gate(id="j", kpi="soft", kind="llm_judge", check="rubric-text"),),
        external_anchor=f"{__import__('plateau.integrity', fromlist=['file_hash']).file_hash(ANCHOR_VERDICT)}@{ANCHOR_VERDICT}",
    )
    with pytest.raises(NotImplementedError, match="llm_judge"):
        evaluate({"anything": True}, v)


def test_loop_requires_real_state_handle():
    """§9.1: a stateless loop is a bug — state_handle must be non-empty at construction."""
    with pytest.raises(ValueError, match="state_handle"):
        LoopConfig(generator_policy="p", max_iterations=4, state_handle="")


def test_loop_requires_max_iterations_wall():
    """§9.2: never a loop without a wall."""
    with pytest.raises(ValueError, match="max_iterations"):
        LoopConfig(generator_policy="p", max_iterations=0, state_handle="h")
