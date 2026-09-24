"""plateau.sigma.run_schema — γ, the inner fixpoint loop, + extract_schema (§2, §6, §10).

`run_schema(schema, model, store) -> RunResult` drives the propose-and-check controller to a
fixpoint:

  each iteration:
    1. HYDRATE context from Φ via the schema's state_handle — the depth paid in prior
       iterations is read back IN, so the generator sees what's already been figured out.
    2. PROPOSE a candidate: model(intent, hydrated_context, iteration) -> candidate.
    3. SCORE against V with evaluate(); record feasibility.
    4. WRITE newly-paid depth back into Φ (fossil_write) AND advance the persisted
       iteration-state under state_handle — so the NEXT pass hydrates strictly more.
    5. STOP per stop_rule (all_gates_pass / budget_exhausted / either) or hit max_iterations.

§9.1 is the crux: `state_handle` is REAL. Iteration-state (best feasibility so far, the depth
fossils paid, the running context) is externalized through Φ, so a longer run COMPOUNDS depth
instead of resampling the same shallow basin. A stateless re-roll would be a bug; the
state-record persisted under state_handle is what makes this a depth-accumulating loop.

`model` is any callable `(intent, context, iteration) -> candidate`. For the slice it is an
injected DETERMINISTIC generator (no live LLM), so the loop + state + fossil-write are
exercised end-to-end in tests.

`extract_schema(session, deliverable, clean_intent) -> Schema` performs the inversion: it
synthesizes a CANDIDATE Schema (ι + V anchored to the real deliverable + γ) good enough to
drive A1. It never claims to recover the literal original prompt (§6) — prompts→outputs is
many-to-one; the job is a generator whose output mass lands on D.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from plateau.integrity import file_hash

from .evaluate import GateResults, evaluate
from .fossils import FossilStore
from .models import Gate, Intent, LoopConfig, Schema, Verifier


# --------------------------------------------------------------- run result ----

@dataclass
class RunResult:
    schema: Schema
    iterations: int
    all_pass: bool
    feasibility: float
    stop_reason: str
    best_candidate: object = None
    results: GateResults = None
    fossils_written: list = field(default_factory=list)
    feasibility_trace: list = field(default_factory=list)   # per-iteration feasibility — must be monotone-non-decreasing if depth compounds
    state_handle: str = ""


# --------------------------------------------------------- Φ-backed loop state ----
# The iteration-state record lives IN Φ (under state_handle). This is what makes the loop
# stateful (§9.1): each pass reads the prior record, extends it, and writes it back.

def _state_key(store: FossilStore, handle: str) -> str:
    # The state record is stored at a deterministic path inside the store root keyed by handle,
    # alongside the content-addressed blobs. It is the loop's externalized scratch — distinct
    # from the immutable depth fossils, which keep their own content addresses.
    safe = handle.replace("/", "_").replace(":", "_")
    return os.path.join(store.root, f"_loopstate_{safe}.json")


def _load_state(store: FossilStore, handle: str) -> dict:
    p = _state_key(store, handle)
    if not os.path.exists(p):
        return {"iteration": 0, "best_feasibility": 0.0, "paid_depth": [], "context": {}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save_state(store: FossilStore, handle: str, st: dict) -> None:
    with open(_state_key(store, handle), "w", encoding="utf-8") as f:
        json.dump(st, f, sort_keys=True)


# ------------------------------------------------------------------ γ — loop ----

def run_schema(schema: Schema, model, store: FossilStore) -> RunResult:
    """Drive γ to the fixpoint. `model(intent, context, iteration) -> candidate`.

    Hydrates context from Φ each pass, scores against the FROZEN V, writes newly-paid depth
    back into Φ, and advances the persisted iteration-state so depth compounds. Honors
    max_iterations + stop_rule (§1.4, §9)."""
    cfg = schema.loop
    handle = cfg.state_handle
    st = _load_state(store, handle)          # HYDRATE persisted iteration-state from Φ

    best_feas = st.get("best_feasibility", 0.0)
    best_candidate = None
    best_results = None
    written = []
    trace = []
    stop_reason = "budget_exhausted"
    done = 0

    for i in range(cfg.max_iterations):
        iteration = st["iteration"] + i
        # 1. HYDRATE: context carries the depth already paid (fossil hashes + prior best).
        context = {
            "paid_depth": list(st.get("paid_depth", [])),
            "best_feasibility": best_feas,
            "prior_context": st.get("context", {}),
            "excluded_paths": list(schema.intent.excluded_paths),
        }
        # 2. PROPOSE
        candidate = model(schema.intent, context, iteration)
        # 3. SCORE against the frozen V
        results = evaluate(candidate, schema.verifier)
        feas = results.feasibility
        trace.append(feas)
        done = i + 1

        # 4. Keep the best; write newly-paid depth back into Φ so the NEXT pass hydrates more.
        improved = feas >= best_feas
        if improved:
            best_feas = feas
            best_candidate = candidate
            best_results = results
        if cfg.fossil_write and improved:
            payload = candidate if isinstance(candidate, (bytes, str)) \
                else json.dumps(candidate, sort_keys=True)
            h = store.put(
                payload,
                provenance={"session": schema.intent.source_session_hash or "session",
                            "turn": iteration, "feasibility": feas},
                satisfies=[r.gate_id for r in results.results if r.passed],
                self_verifiable=True,
            )
            if h not in st.get("paid_depth", []):
                st.setdefault("paid_depth", []).append(h)
            written.append(h)

        # advance + PERSIST iteration-state through Φ (this is the REAL state_handle, §9.1)
        st["iteration"] = iteration + 1
        st["best_feasibility"] = best_feas
        st["context"] = {"last_feasibility": feas, "last_iteration": iteration}
        _save_state(store, handle, st)

        # 5. STOP
        if results.all_pass and cfg.stop_rule in ("all_gates_pass", "either"):
            stop_reason = "all_gates_pass"
            break
    else:
        if cfg.stop_rule in ("budget_exhausted", "either"):
            stop_reason = "budget_exhausted"

    return RunResult(
        schema=schema,
        iterations=done,
        all_pass=bool(best_results and best_results.all_pass),
        feasibility=best_feas,
        stop_reason=stop_reason,
        best_candidate=best_candidate,
        results=best_results,
        fossils_written=written,
        feasibility_trace=trace,
        state_handle=handle,
    )


# --------------------------------------------------------------- inversion ----

def extract_schema(session, deliverable, clean_intent) -> Schema:
    """Σ inversion (§6): synthesize a CANDIDATE Schema from a session + the real deliverable.

    Produces ι (from clean_intent), V anchored EXTERNALLY to the deliverable on disk, and a γ
    LoopConfig with a real state_handle. The result is a candidate generator-spec, never a
    proven inverse — it must be tested via run_schema + evaluate (that test IS A1).

    Arguments:
      session       — dict-ish trajectory record (provides provenance / source_session_hash).
      deliverable   — dict with at least {"path": <on-disk path to D>}; the external anchor.
      clean_intent  — dict with goal / target_invariants / constraints / excluded_paths.
    The caller supplies the gate set in deliverable["gates"] (the real KPIs of D); extraction
    does not invent KPIs — it carries the deliverable's own checkable properties forward."""
    path = deliverable["path"]
    if not os.path.exists(path):
        raise FileNotFoundError(f"anchor deliverable not found: {path}")
    anchor_hash = file_hash(path)
    # external_anchor binds BOTH the content hash AND the path — resolves outside the loop.
    external_anchor = f"{anchor_hash}@{path}"

    session_hash = ""
    if isinstance(session, dict):
        session_hash = session.get("session_hash", "") or session.get("hash", "")
    if not session_hash:
        # derive a stable provenance hash from the session record itself
        session_hash = "sha256:" + __import__("hashlib").sha256(
            json.dumps(session, sort_keys=True, default=str).encode()).hexdigest()

    intent = Intent(
        goal=clean_intent["goal"],
        target_invariants=tuple(clean_intent.get("target_invariants", ())),
        constraints=tuple(clean_intent.get("constraints", ())),
        excluded_paths=tuple(clean_intent.get("excluded_paths", ())),
        source_session_hash=session_hash,
    )

    gates = tuple(
        g if isinstance(g, Gate) else Gate(**g)
        for g in deliverable["gates"]
    )
    verifier = Verifier(gates=gates, external_anchor=external_anchor)

    loop = LoopConfig(
        generator_policy=deliverable.get("generator_policy", "propose-and-check"),
        max_iterations=int(deliverable.get("max_iterations", 8)),
        stop_rule=deliverable.get("stop_rule", "either"),
        state_handle=f"sigma/{session_hash[:16]}/{verifier.frozen_hash[7:23]}",
        fossil_write=True,
    )
    return Schema(intent=intent, verifier=verifier, loop=loop, phi=())
