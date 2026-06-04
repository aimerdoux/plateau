"""bench_summary — print the sourced metrics from the live wavex-os agency run.

Read-only. This does NOT run anything and does NOT recompute the figures; it prints the
numbers exactly as recorded in the sealed run reports, with each one labelled by its source
section, so the README/BENCHMARKS table can be reproduced in the terminal:

    python -m plateau.agency.bench_summary

Authoritative sources (LOCAL, unpublished):
  - wavex-os/.plateau-agency/reports/AGENCY_RUN_REPORT.md   (parent run: §1/§3/§4/§5/§6)
  - wavex-os/.plateau-agency/reports/FLEET_REPORT.md        (the 19-agent fleet beneath it)

Numbers that are explicitly MODELLED ESTIMATES in the source report (the ~202 hypothetical
compactions and the USD cost) are labelled as such. Every other number is a real meter/API read.
Where the run brief's round estimate disagreed with the live API, the live API value is shown
(the brief estimate is noted in parentheses) — same discipline as the sealed demos.
"""

from __future__ import annotations

# --- §1/§3/§4 AGENCY_RUN_REPORT.md: the bounded-parent run (real meter/API reads) ---
PARENT_RUN = {
    "bounded_orchestrators": 4,                    # §1
    "parent_compactions": 0,                       # §1, §5
    "orch_signal_total_tok": 76_030,               # §3 aggregate
    "per_step_signal_band_tok": (300, 1_700),      # §3
    "worker_cache_read_tok": 40_230_750,           # §3 aggregate
    "worker_input_tok": 154_917,                   # §3 aggregate
    "worker_output_tok": 238_753,                  # §3 aggregate
    "worker_grand_total_tok": 40_624_420,          # §3 aggregate (in+out+cache_read)
    "bypass_tok": 40_385_667,                      # §4 (cache_read + input)
    "bypass_to_signal_ratio": 531,                 # §4 (40,385,667 / 76,030) — observed this run
    "peak_step_cache_read_tok": 7_294_973,         # §3 (fleet-launch step 13, resume-API worker)
    "total_findings": 115,                         # §3 aggregate
    "work_steps": 51,                              # §3 (excl. 50 poll waits)
    "seq_equiv_hours": 2.40,                       # §3 (8,650 s)
    "prs_emitted": 3,                              # §1, §6.A — all OPEN, NEVER merged (by design)
    "hypothetical_inline_compactions_ESTIMATE": 202,   # §5 — explicitly MODELLED estimate
    "usd_cost_ESTIMATE_range": (16, 35),               # §3 — explicitly labelled estimate
}

# --- FLEET_REPORT.md: the 19-agent fleet (live Paperclip control-plane API) ---
FLEET = {
    "agents": 19,                  # §1 roster (all claude-sonnet-4-6)
    "issues_total": 500,           # §2
    "issues_done": 439,            # §2 (88%) — live API authoritative; brief estimated ~441
    "heartbeat_runs": 2_499,       # §3 — live API; brief estimated ~2,482
    "run_success_rate_pct": 83.1,  # §3 (2,076 succeeded)
    "upstream_ratelimit_failures": "207 of 296 (70%)",  # §3 — infra ceiling, not agent logic
}


def _fmt(n: int) -> str:
    return f"{n:,}"


def render() -> str:
    p, f = PARENT_RUN, FLEET
    lo, hi = p["per_step_signal_band_tok"]
    ulo, uhi = p["usd_cost_ESTIMATE_range"]
    lines = [
        "Plateau — live wavex-os agency run (LOCAL, unpublished; numbers sourced to the sealed reports)",
        "=" * 84,
        "",
        "THE BOUNDED-PARENT RUN  (AGENCY_RUN_REPORT.md §1/§3/§4)",
        f"  Bounded orchestrators ............. {p['bounded_orchestrators']}"
        "   (connectors / fleet-observe / fleet-launch / onboarding)",
        f"  Parent compactions ............... {p['parent_compactions']}   <- footprint stayed flat",
        f"  Orchestrator signal (total) ...... {_fmt(p['orch_signal_total_tok'])} tok"
        f"   (per-step band {_fmt(lo)}-{_fmt(p['per_step_signal_band_tok'][1])})",
        f"  Worker context that BYPASSED parent {_fmt(p['bypass_tok'])} tok  (cache_read + input)",
        f"  Bypass : signal ratio ............ ~{p['bypass_to_signal_ratio']} : 1   (observed for this run)",
        f"  Peak single-step cache_read ...... {_fmt(p['peak_step_cache_read_tok'])} tok"
        "   (discarded with its worker)",
        f"  Findings / work steps ............ {p['total_findings']} findings over {p['work_steps']} steps"
        f"  (~{p['seq_equiv_hours']}h seq-equiv)",
        f"  PRs emitted ...................... {p['prs_emitted']}   (all OPEN, NEVER merged - by design)",
        "",
        "  [ESTIMATE] inline single-agent would have hit "
        f"~{p['hypothetical_inline_compactions_ESTIMATE']} forced compactions (modelled, §5)",
        f"  [ESTIMATE] run cost ~${ulo}-{uhi} (modelled, §3)",
        "",
        "THE 19-AGENT FLEET BENEATH IT  (FLEET_REPORT.md, live Paperclip API)",
        f"  Agents ........................... {f['agents']}  (all claude-sonnet-4-6)",
        f"  Issues ........................... {f['issues_done']} done / {f['issues_total']}"
        f"  ({round(100 * f['issues_done'] / f['issues_total'])}%)   [live API; brief est. ~441]",
        f"  Heartbeat runs ................... {_fmt(f['heartbeat_runs'])}"
        f"  ({f['run_success_rate_pct']}% success)   [live API; brief est. ~2,482]",
        f"  Upstream rate-limit failures ..... {f['upstream_ratelimit_failures']}  (infra ceiling, not agent logic)",
        "",
        "Sources: wavex-os/.plateau-agency/reports/{AGENCY_RUN_REPORT,FLEET_REPORT}.md",
        "Full sourced table + sealed-demo numbers: BENCHMARKS.md ; re-verify: RESULTS.md",
    ]
    return "\n".join(lines)


def main() -> None:
    print(render())


if __name__ == "__main__":
    main()
