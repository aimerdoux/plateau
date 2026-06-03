#!/usr/bin/env python3
"""External QA-hardening driver (Option 1).

The orchestrator is THIS process. Its entire memory is signal.json on disk; it
does not grow. Each step spawns a fresh `claude -p` (clean context), captures
its JSON to a local var, gates it deterministically, persists, and discards.

Default mode is `audit` (no commits, no PRs). `write` mode is opt-in.

Usage:
  python driver.py --repo /path/to/repo [--mode audit|write]
                   [--max-steps 80] [--target-seconds 7200] [--pr-cap 8]
                   [--run-id ID] [--resume runs/ID/RESUME.json] [--stub]
"""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

from . import bootstrap, gate, prompts, pr, state
from .config import load_config

HERE = Path(__file__).resolve().parent
RESUME_CEIL = 2
WALL_CLOCK_CEIL = 3 * 3600  # 3h across resumes


# ----------------------------------------------------------- utilities ----

def now():
    return time.time()


def git_head(repo):
    rc, out, _ = gate.run(["git", "rev-parse", "HEAD"], repo, timeout=30)
    return out.strip() if rc == 0 else "?"


def append_jsonl(path, record):
    """Append one line; never reads the file back into memory."""
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def extract_json(text):
    """Pull the single JSON object the agent printed as its final message."""
    if not text:
        return None
    try:
        return json.loads(text.strip())
    except ValueError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except ValueError:
            return None
    return None


# ------------------------------------------------------------ spawn step --

def spawn_agent(prompt_text, mode, repo, max_turns=20):
    """One fresh `claude -p` process. Returns parsed agent dict or an error."""
    tools = prompts.AUDIT_TOOLS if mode == "audit" else prompts.WRITE_TOOLS
    cmd = [
        "claude", "-p", prompt_text,
        "--output-format", "json",
        "--permission-mode", "acceptEdits",
        "--max-turns", str(max_turns),
        "--allowedTools", *tools,
        "--disallowedTools", *prompts.DISALLOWED_TOOLS,
        "--append-system-prompt", prompts.SAFETY_FLOOR,
    ]
    rc, out, err = gate.run(cmd, repo, timeout=600)
    if rc != 0 and not out:
        return {"class": "blocked", "carry": "agent exit %d: %s" % (rc, err[:80]),
                "clean": False, "evidence": [], "edited_files": []}
    envelope = extract_json(out)
    result_text = ""
    if isinstance(envelope, dict):
        result_text = envelope.get("result") or envelope.get("text") or ""
    inner = extract_json(result_text) or (envelope if _looks_like_result(envelope) else None)
    if not isinstance(inner, dict):
        return {"class": "blocked", "carry": "unparseable agent output",
                "clean": False, "evidence": [], "edited_files": []}
    inner.setdefault("evidence", [])
    inner.setdefault("edited_files", [])
    inner.setdefault("carry", "")
    return inner


def _looks_like_result(obj):
    return isinstance(obj, dict) and "class" in obj and "evidence" in obj


def stub_agent(item, mode):
    """Deterministic canned result for machinery testing (no claude call)."""
    pk = "stub:" + item["id"]
    return {
        "class": "audit",
        "clean": False,
        "carry": "stub finding for %s" % item["id"],
        "evidence": [{"check": "stub static read", "location": item["id"],
                      "observed": "stubbed observation"}],
        "finding": "STUB finding on %s" % item["id"],
        "recommendation": "stub recommendation",
        "pattern_key": pk,
        "edited_files": [],
    }


# -------------------------------------------------- gate: audit vs fix ----

def gate_audit(agent, item):
    """Pure-python gate for audit class. Returns (outcome, covered_bool, facts)."""
    ev = agent.get("evidence") or []
    if agent.get("clean"):
        if not ev:
            return "rejected", False, []   # clean audit w/o evidence is INVALID
        return "gated", True, []           # clean-with-evidence covers the item
    # a finding: requires evidence + a concrete anchor
    finding = agent.get("finding")
    has_anchor = bool(ev) and any(e.get("location") for e in ev)
    if finding and has_anchor:
        return "found", True, []
    return "rejected", False, []


def gate_fix(agent, item, repo, artifact_dir, step, cfg=None):
    """Deterministic gate for write/fix class. Driver does staging + scan + gate.
    Returns (outcome, covered_bool, facts, reject_reason)."""
    files = [f for f in (agent.get("edited_files") or []) if f]
    if not files:
        return "rejected", False, [], "fix class but no edited_files"

    # explicit path-scoped staging only -- never git add -A/./-u
    gate.run(["git", "reset", "-q"], repo)
    gate.run(["git", "add", "--"] + files, repo)

    cls = gate.classify_diff(repo)
    if cls["secret_paths"]:
        gate.run(["git", "reset", "-q"], repo)
        return "quarantined", False, [], "secret path staged: %s" % cls["secret_paths"]

    if cls["touches_config"]:
        gate.run(["git", "reset", "-q"], repo)
        return "needs_review", False, [], "touches gate/config -> audit-only"

    # Phase 6.5 -- non-negotiable: any denylist hit rejects, green or not.
    hits = gate.scan_diff_policy(gate.staged_diff(repo), (cfg or {}).get("denylist_extra", []))
    if hits:
        gate.run(["git", "reset", "-q"], repo)
        return "rejected", False, [], "diff-policy hit: %s" % hits[0]["pattern"]

    if not cls["touches_logic"]:
        return "trivial", False, [], "no logic change"

    # run the real gate (driver runs it -> independent re-verification)
    _, verdict = gate.run_gate(item["kind"], repo, artifact_dir, classify=cls, cfg=cfg)
    if not verdict.get("normalized_pass"):
        gate.run(["git", "reset", "-q"], repo)
        return "rejected", False, [], "gate failed: exit=%s empty=%s" % (
            verdict.get("exit_code"), verdict.get("empty_suite"))

    # admit: bind each changed file's CURRENT sha256 as a verified fact
    facts = []
    for f in files:
        h = state.sha256_file(Path(repo) / f)
        if h:
            facts.append({"file": f, "sha256": h, "step": step})
    facts.append({"result": str(Path(artifact_dir) / "result.json"),
                  "sha256": state.sha256_file(Path(artifact_dir) / "result.json")})
    return "gated", True, facts, None


# ------------------------------------------------------------- resume -----

def write_resume(run_dir, sig, last_step, cov_path, by_tier, counters):
    sig = state.enforce_caps(sig)
    resume = {
        "run_id": sig["run_id"], "run_start": sig["run_start"],
        "elapsed": now() - sig["run_start"], "last_step": last_step,
        "resume_count": sig.get("resume_count", 0),
        "signal_digest": state.compact_signal(sig, max_bytes=4000),
        "coverage_path": str(cov_path), "coverage_by_tier": by_tier,
    }
    resume.update(counters)  # gated_completions, findings_repro, prs_open, stall
    rp = Path(run_dir) / "RESUME.json"
    state.save_json(rp, resume)
    return rp


# -------------------------------------------------------------- main ------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--mode", choices=["audit", "write"], default="audit")
    ap.add_argument("--run-id", default=time.strftime("%Y%m%dT%H%M%S"))
    ap.add_argument("--max-steps", type=int, default=80)   # STEP_BUDGET
    ap.add_argument("--target-seconds", type=int, default=7200)
    ap.add_argument("--pr-cap", type=int, default=8)
    ap.add_argument("--resume", default=None)
    ap.add_argument("--stub", action="store_true",
                    help="use a canned agent result (no claude call) to test machinery")
    ap.add_argument("--config", default=None,
                    help="JSON config override path; else auto-detected from the repo")
    ap.add_argument("--base", default="main", help="base branch for PRs (write mode)")
    ap.add_argument("--dry-run-pr", action="store_true",
                    help="write mode: build the branch + PR body locally, do NOT push or open a PR")
    args = ap.parse_args()

    repo = str(Path(args.repo).resolve())
    cfg = load_config(repo, args.config)

    # Resume must bind to the ORIGINAL run's dir, not a fresh timestamp.
    resume_blob = None
    if args.resume:
        resume_blob = state.load_json(args.resume, None)
        if not resume_blob:
            print("RESUME file unreadable:", args.resume); return
        if resume_blob.get("resume_count", 0) >= RESUME_CEIL:
            print("resume ceiling reached; writing final summary, no re-invoke.")
            return
        run_id = resume_blob["run_id"]
    else:
        run_id = args.run_id

    run_dir = HERE / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    cov_path = run_dir / "coverage.json"
    sig_path = run_dir / "signal.json"
    ledger = run_dir / "ledger.jsonl"
    kpis = run_dir / "kpis.jsonl"
    quarantine = run_dir / "quarantine.jsonl"
    findings_md = run_dir / "FINDINGS.md"

    # cumulative counters survive resume.
    stall = prs_open = gated_completions = findings_repro = 0

    if resume_blob is not None:
        r = resume_blob
        sig = json.loads(r["signal_digest"])
        sig["run_id"] = run_id; sig["run_start"] = r["run_start"]
        sig["resume_count"] = r.get("resume_count", 0) + 1
        coverage = state.load_json(cov_path, [])
        start_step = r.get("last_step", 0) + 1
        gated_completions = r.get("gated_completions", 0)
        findings_repro = r.get("findings_repro", 0)
        prs_open = r.get("prs_open", 0)
        stall = r.get("stall", 0)
    else:
        run_start = now()
        sig = state.new_signal(run_id, run_start)
        coverage = bootstrap.build_coverage(repo, cfg)
        state.save_json(cov_path, coverage)
        start_step = 1

    run_start = sig["run_start"]
    sig["pointers"]["repo"] = repo
    sig["pointers"]["head"] = git_head(repo)

    step = start_step
    stop_reason = "loop-exited"

    while True:
        elapsed = now() - run_start

        # ORCHESTRATOR-CONTEXT-SAFEGUARD: deterministic step budget.
        if step - start_step >= args.max_steps:
            _, by_tier = state.cov_counts(coverage)
            rp = write_resume(run_dir, sig, step - 1, cov_path, by_tier, {
                "gated_completions": gated_completions, "findings_repro": findings_repro,
                "prs_open": prs_open, "stall": stall})
            print("CHECKPOINT step_budget. resume:")
            print("  plateau-qa --repo %s --resume %s" % (repo, rp))
            stop_reason = "step_budget_checkpoint"; break
        if elapsed > WALL_CLOCK_CEIL:
            stop_reason = "wall_clock_ceiling"; break

        # Phase 1 INFLATE -- re-ground; evict stale open-item facts.
        sig["pointers"]["head"] = git_head(repo)
        kept = []
        for fct in sig.get("verified_facts", []):
            f = fct.get("file")
            if f and state.sha256_file(Path(repo) / f) != fct.get("sha256"):
                continue  # file changed -> fact stale, drop
            kept.append(fct)
        sig["verified_facts"] = kept
        state.enforce_caps(sig)
        by_status, by_tier = state.cov_counts(coverage)

        # Phase 2 TRIAGE -- ascending tier; None => backlog drained.
        item = state.next_pending(coverage)
        if item is None:
            target_met = elapsed >= args.target_seconds
            stop_reason = "backlog_drained target_met=%s" % target_met
            break

        item["status"] = "in_progress"
        state.save_json(cov_path, coverage)

        # Dedupe pre-check is post-return (needs pattern_key from agent).
        # Phase 3 SPAWN (fresh context) -- Phase 4 parse one JSON object.
        artifact_dir = run_dir / str(step)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        if args.stub:
            agent = stub_agent(item, args.mode)
        else:
            ptext = prompts.build_subtask(
                state.compact_signal(sig), item, args.mode, repo, args.run_id, step)
            agent = spawn_agent(ptext, args.mode, repo)

        cls = agent.get("class", "blocked")
        pk = agent.get("pattern_key")

        # Dedupe.
        if pk and state.pattern_seen(ledger, pk):
            outcome, covered, facts, reason = "duplicate", True, [], None
        elif cls == "blocked":
            outcome, covered, facts, reason = "quarantined", False, [], agent.get("carry", "blocked")
        elif args.mode == "write" and cls == "fix":
            outcome, covered, facts, reason = gate_fix(agent, item, repo, artifact_dir, step, cfg)
        else:
            o, covered, facts = gate_audit(agent, item)
            outcome, reason = o, None

        # Phase 5/6 already done deterministically above. Phase 7 PERSIST.
        if outcome == "quarantined":
            append_jsonl(quarantine, {"step": step, "id": item["id"],
                                      "reason": reason or agent.get("carry", "")})
            item["status"] = "quarantined"
        elif covered:
            item["status"] = "covered"
            item["pattern_key"] = pk
            item["last_gated_step"] = step
            if facts:
                state.set_open_item_facts(sig, facts)
            if outcome == "gated" and cls == "fix":
                gated_completions += 1
                if args.mode == "write" and prs_open < args.pr_cap:
                    prr = pr.open_pr(repo, item, agent, facts, step, artifact_dir,
                                     base=args.base, dry_run=args.dry_run_pr)
                    if prr.get("opened"):
                        prs_open += 1
                    append_jsonl(ledger, {"step": step, "id": item["id"], "pr": prr})
            if outcome == "found":
                findings_repro += 1
                _append_finding(findings_md, step, item, agent)
        else:
            # rejected / trivial / needs_review -> not covered; revert to pending
            item["status"] = "pending" if outcome in ("rejected",) else "covered"
            if outcome in ("needs_review", "trivial"):
                item["last_gated_step"] = step
                if outcome == "needs_review":
                    _append_finding(findings_md, step, item, agent, tag="needs-review")

        state.add_lesson(sig, agent.get("carry", ""))
        sig["stance"] = "step %d done (%s); tier focus continues" % (step, outcome)
        state.save_json(cov_path, coverage)
        state.save_json(sig_path, sig)

        # ledger (audit trail) -- shell-append equivalent, never read back.
        append_jsonl(ledger, {"step": step, "id": item["id"], "kind": item["kind"],
                              "tier": item["tier"], "outcome": outcome,
                              "pattern_key": pk, "reason": reason})

        # stall: no fix admitted AND no repro finding -> increment.
        if outcome in ("gated",) and cls == "fix":
            stall = 0
        elif outcome == "found":
            stall = 0
        else:
            stall += 1

        # Phase 8 KPI (shed everything else).
        _, by_tier = state.cov_counts(coverage)
        sec = by_tier["sec"]
        append_jsonl(kpis, {
            "step": step, "elapsed_s": round(elapsed),
            "target_met": elapsed >= args.target_seconds,
            "gated_completions": gated_completions, "prs_opened": prs_open,
            "coverage_by_tier": by_tier,
            "sec_coverage_pct": _pct(sec["covered"], sec["total"]),
            "findings_with_repro": findings_repro, "picked_item": item["id"],
            "outcome": outcome, "stall_counter": stall,
            "resume_count": sig.get("resume_count", 0),
        })
        print("step %d | t=%ds | sec=%d/%d | gated=%d | PRs=%d | find(repro)=%d | last=%s:%s"
              % (step, round(elapsed), sec["covered"], sec["total"],
                 gated_completions, prs_open, findings_repro, item["id"], outcome))

        # availability-floor degeneracy note (informational here).
        if stall >= 5:
            state.add_lesson(sig, "stall>=5: clean-only streak; jump tier-family")

        step += 1

    # ---- final ----
    state.save_json(sig_path, sig)
    _, by_tier = state.cov_counts(coverage)
    print("STOP reason=%s steps=%d gated=%d findings_repro=%d by_tier=%s"
          % (stop_reason, step - start_step, gated_completions, findings_repro, by_tier))
    print("artifacts: %s" % run_dir)


def _pct(c, t):
    return round(100.0 * c / t, 1) if t else 0.0


def _append_finding(path, step, item, agent, tag="finding"):
    lines = ["\n## [%s] step %d — %s (`%s`, tier %d)\n" %
             (tag, step, item["id"], item["kind"], item["tier"])]
    if agent.get("finding"):
        lines.append("**Finding:** %s\n" % agent["finding"])
    for e in agent.get("evidence", []):
        lines.append("- `%s` — %s: %s" %
                     (e.get("location", "?"), e.get("check", ""), e.get("observed", "")))
    if agent.get("recommendation"):
        lines.append("\n**Recommendation:** %s\n" % agent["recommendation"])
    with open(path, "a") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
