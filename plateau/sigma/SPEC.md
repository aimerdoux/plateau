# Plateau — The Σ Operator
### Implementation work order: schema-inversion + self-improvement subsystem
**Status:** design-locked / implementation-open
**Loyalty clause:** this abstraction *is* the spec. Do not flatten Σ into a generic "prompt manager," templating library, or RAG cache. If a decision would erase one of the four carriers or soften the §3 invariant, it is wrong by definition — escalate instead of simplifying.

## 0. One mental model
One object at three altitudes: *a verifier-carrying, fossil-backed fixpoint operator closed under its own application.*
- **Inner:** the operator searches for a deliverable `D` (propose → check → repeat until the verifier fires).
- **Outer:** the *same* search refines the operator itself across sessions.
- **Calibration:** the *same* search locates how much a given model can decompress — how we measure the model.
Plateau provides the substrate (bounded context + content-addressed/hashed storage). Σ runs **on top of** it.

## 1. The core object
`Σ = ⟨ ι , V , Φ , γ ⟩` — a Schema is exactly four load-bearing carriers.

### 1.1 ι — clean intent
Fixpoint of multi-turn intent discovery, false starts stripped. Compression of trajectory → target: *what* the deliverable is, never *how* we figured it out. Remove it → you compress the wrong thing and reconstruct the session, not the deliverable.
```python
class Intent(BaseModel):
    goal: str                      # destination, stated once, cleanly
    target_invariants: list[str]   # properties that make D *this* deliverable, not a neighbor
    constraints: list[str]         # hard limits D must respect
    excluded_paths: list[str]      # approaches proven dead — negative information is information
    source_session_hash: str       # provenance
```
`excluded_paths` carries forward ruled-out dead ends so a weaker decoder doesn't re-pay for known failures.

### 1.2 V — verifier (the gate set) — LOAD-BEARING
Decomposed set of checkable gates, each anchored to a KPI of the real deliverable. V is the operational definition of "is this D." Short because recognizing ≪ producing (`K(V) ≪ K(D)`). Remove it → no feasibility signal, no stop rule, and the outer loop collapses into self-satisfaction.
```python
class Gate(BaseModel):
    id: str
    kpi: str
    kind: Literal["programmatic", "test", "llm_judge"]
    check: str                     # code ref, test ref, or rubric per kind
    threshold: float
    weight: float
class Verifier(BaseModel):         # FROZEN/immutable (see §3)
    gates: list[Gate]
    external_anchor: str           # REQUIRED, non-empty, resolves OUTSIDE the loop
    frozen_hash: str               # content hash of the gate set, computed at construction
```
decidable gates (programmatic/test) can report **failure** → true semi-decision. `llm_judge` gates confirm success only with confidence — soft, never the sole gate on a critical KPI. `external_anchor` is non-negotiable; a verifier with no external anchor is rejected at construction.

### 1.3 Φ — fossils (paid logical depth, content-addressed)
Cache of logical depth already paid for (Bennett). Depth paid once, hashed, never re-spent. Plateau-native: content-addressing, integrity, cross-session dedup. Remove it → a weaker/single-shot decoder must re-derive what it can't afford in one pass.
```python
class Fossil(BaseModel):
    hash: str                      # content address (integrity + dedup key)
    artifact: bytes | str          # cached expensive result
    satisfies: list[str]           # gate ids this helps satisfy
    self_verifiable: bool          # receiver can re-check without re-deriving?
    provenance: dict               # session hash, turn index, cost paid
```
Dedup is a feature: same depth → same hash → second session reuses the first. Measure it (§7 A3).

### 1.4 γ — the loop (search operator)
Propose-and-check controller driving to the fixpoint (`/loop` made concrete). generator + verifier + iteration ⇒ a semi-decision procedure (Levin-search-shaped): halts-and-succeeds if a reachable solution exists, may run forever otherwise. Halting is *bounded* by explicit budget, not solved. Remove it → a static spec that fails the instant depth exceeds one pass.
```python
class LoopConfig(BaseModel):
    generator_policy: str
    max_iterations: int            # REQUIRED wall
    stop_rule: Literal["all_gates_pass", "budget_exhausted", "either"]
    state_handle: str              # pointer into Φ — iteration-state persists here (REAL, not a stub)
    fossil_write: bool             # successful expensive sub-results hashed back into Φ
```
**Critical (§9):** an LLM loop is NOT a Turing machine (finite context, not unbounded tape). A memoryless re-roll resamples the same shallow basin — it buys breadth, not depth. `state_handle` MUST externalize iteration-state through Φ so depth compounds. A stateless loop is a bug.

## 2. Operators
- **γ — inner search:** `run_schema(schema, model) -> RunResult` — drive the loop with `model`, hydrate context from Φ each iteration, write newly-paid depth back to Φ, score against V until `stop_rule` fires.
- **𝒮 — outer self-improvement:** `refine(schema, outcomes) -> Schema` — same fixpoint search at the schema altitude. MAY rewrite ι, Φ, γ. MUST NOT rewrite V. Returns a NEW Schema with the SAME `Verifier.frozen_hash`. A mature `Σ*` is the fixpoint of 𝒮.

## 3. The invariant (constitution-first — NON-NEGOTIABLE)
> Within a session, V is immutable. 𝒮 may rewrite ι, Φ, γ. 𝒮 may NEVER rewrite V.
The single rule separating self-improvement from drift. An unanchored outer loop optimizes Σ to pass gates it also authored → collapses into a private idiolect. Externally-anchored gates hold the loop inside a *shared* language. Enforce structurally:
1. `Verifier` frozen (immutable); `frozen_hash` computed at construction.
2. `refine()` takes V read-only, returns a new Σ carrying the SAME `frozen_hash`.
3. Runtime assertion + a unit test that *attempts* mutation and expects failure:
   `assert refined.verifier.frozen_hash == original.verifier.frozen_hash, "INVARIANT VIOLATION: V mutated"`
4. `external_anchor` must be non-empty and resolve outside the loop, else rejected at construction.
A genuinely different verifier = a NEW session with a new V, not in-session mutation.

## 4. Valuation harness — `v(M)` (research-grade)
Decoder-relative: minimal prompt length ≈ `K(D | π_M)`; feasible depth bounded by per-pass compute `C_M`. Pre-register ladder, `k`, `ε` before running.
1. Compression ladder of prompts `P_λ` (λ=0 full session → λ=L max abstraction), lengths strictly decreasing.
2. Run each `P_λ` against `M` exactly `k` times. `s_M(λ)` = pass-rate vs V (monotone-decreasing in λ — sanity check).
3. `v(M) = sup{ λ : s_M(λ) ≥ 1−ε }`; `ℓ(v(M))` estimates `K(D | π_M)`.
Two ladders: **length@fixed-depth** → prior `π_M` → `λ*_len`; **depth@fixed-length** → per-pass compute `C_M` → `λ*_depth`. So `v(M) = (λ*_len, λ*_depth)`. Rate-distortion (curve, distortion=1−s) × IRT (λ* = ability). Application is the experiment.
`valuate(model, deliverable, verifier, ladder, k, epsilon) -> ModelValue` — runs the two-ladder protocol; pre-registration manifest hashed + stored before any run.

## 5. Fossil layer (Φ) — content-addressing
On Plateau's existing content-addressed store (`plateau.integrity.file_hash`). `put(artifact)->hash` (identical content ⇒ identical hash ⇒ dedup); `get(hash)->artifact` (integrity-checked; mismatch = hard error); provenance mandatory on write; cross-session dedup is the headline — measure + report reuse. The maximally compressed handoff = instruction + cached residue of the expensive search (keep surprising/expensive, drop derivable).

## 6. API surface
```
extract_schema(session, deliverable, clean_intent) -> Schema   # inversion → a CANDIDATE, must be tested
run_schema(schema, model) -> RunResult                         # γ inner loop
evaluate(candidate, verifier) -> GateResults                   # run gates
refine(schema, outcomes) -> Schema                             # 𝒮, §3 enforced
valuate(model, deliverable, verifier, ladder, k, epsilon) -> ModelValue
fossils.put(artifact)->hash ; fossils.get(hash)->artifact ; fossils.reuse_report()->ReuseStats
```
`extract_schema` produces a CANDIDATE, never a proven inverse (prompts→outputs is many-to-one). Synthesize a short robust member of the set whose output mass is on `D`, then test via run_schema+evaluate. Recovering "the literal original prompt" is out of scope; engineering a generator that reproduces D is the job.

## 7. Acceptance criteria (anchored to a REAL logged Plateau deliverable + its V)
| # | Criterion | Type |
|---|-----------|------|
| A1 | Round-trip: extract_schema then run_schema on same model passes all gates ≥ τ (pre-registered) | proven-property |
| A2 | V-immutability: over N refine() steps frozen_hash constant; mutation attempt fails | proven-property |
| A3 | Fossil dedup: two sessions paying same depth → hash collision; reuse_report shows reuse | proven-property |
| A4 | Ladder monotonicity: s_M(λ) monotone-decreasing on both ladders | sanity gate |
| A5 | Valuation separation: distinct (λ*_len, λ*_depth) for two models of known differing capability; stronger dominates both | research-grade |
| A6 | Anti-drift: under refine() with anchored V, output stays gate-passing across sessions, does NOT specialize into outputs only its own judge accepts | research-grade |
A1–A4 must pass to ship. A5–A6 measured + reported, not assumed.

## 8. Solid vs research-grade
**SOLID (rely on):** `K(V)≪K(D)` asymmetry; depth-uncompressibility ⇒ Φ necessary; V-immutability anti-drift (§3); content-addressed fossils + cross-session dedup.
**RESEARCH-GRADE (instrument, flag, don't assume):** convergence/non-collapse of 𝒮 (A6 tests); manifold regularity / one-schema-generalizes (A5 probes); exact shape of v(M) (§4 measures). Negative results are first-class.

## 9. Constraints & failure modes
1. LLM ≠ Turing machine — γ must externalize state through Φ or it accumulates breadth not depth. Stateless loop = bug.
2. Halting bounded, not solved — Rice forbids deciding success in advance; `max_iterations` is the wall. Never ship a loop without one.
3. Drift is the default failure — unanchored 𝒮 collapses to a one-mind cache. §3's anchored immutable V is the only guard. If A6 shows judge-specialization, the anchor is leaking — fix the anchor, never relax the invariant.
4. extract_schema is lossy + non-unique — compresses intent, reconstructs deliverable not trajectory.

## 10. Smallest shippable slice (START HERE)
1. `Schema, Intent, Gate, Verifier, Fossil, LoopConfig` models with §3 enforcement wired into `Verifier` construction.
2. `fossils.put/get/reuse_report` on Plateau's content-addressed store (`plateau.integrity.file_hash`).
3. `evaluate(candidate, verifier)` for `programmatic` + `test` gate kinds (defer `llm_judge`).
4. `run_schema` with a minimal γ that hydrates from Φ and writes fossils back — `state_handle` REAL, not a stub.
5. A1, A2, A3 passing on one real anchor deliverable.
`refine` (𝒮), `valuate` (two-ladder), and `llm_judge` gates come AFTER the slice proves inner loop + invariant + fossil layer. Do not build the outer loop before the inner loop is anchored — that ordering is the anti-drift principle applied to the build.

*Build the inner fixpoint first. Anchor the verifier externally. Let depth fossilize. Only then close the loop on itself.*
