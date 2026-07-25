# PLAN — control-loop self-hosting run

Gates are written BEFORE work starts (P3). Row grammar is fixed and machine-parsed by
`plateau.agency.control.parse_plan`. EXPECT is `exit0` or a substring of the gate's output.
Critical path: T1 → T2 → T3 → (T4 ‖ T6) → T5 → T7 → T8.

- [x] T1 | control CLI: `python -m plateau.agency.control` with init/status/verify subcommands | plateau/agency/__main__.py + control.py CLI | GATE: python -m plateau.agency.control verify --control-dir .plateau/control --json | EXPECT: "unchecked"
- [ ] T2 | loop operating artifacts: append_journal / write_blocked / read_status helpers in control.py | plateau/agency/control.py | GATE: python -c "from plateau.agency import control as c; assert all(hasattr(c,n) for n in ('append_journal','write_blocked','read_status')); print('HELPERS_OK')" | EXPECT: HELPERS_OK
- [ ] T3 | tests for the CLI + helpers (journal append, blocked round-trip, status verdict, CLI exit codes) | tests/test_control_cli.py | GATE: python -m pytest -q tests/test_control_cli.py | EXPECT: exit0
- [x] T4 | pre-registration for the control-loop demonstration (honest, NULL live, sealed before any measurement) | demo/demo7_prereg.md | GATE: test -f demo/demo7_prereg.md && grep -qi "NULL" demo/demo7_prereg.md && grep -qi "decision rule" demo/demo7_prereg.md | EXPECT: exit0
- [ ] T5 | run the pre-registered demonstration and SEAL raw records under plateau.integrity before scoring | demo/raw7/ + demo/demo7_readout.md | GATE: python demo/score_demo7.py --verify | EXPECT: RECOMPUTE_OK
- [x] T6 | docs: control loop in README + adapter docs, every claim traced to a test or sealed artifact | README.md | GATE: grep -q "orchestrate" README.md && grep -q "control loop" README.md | EXPECT: exit0
- [ ] T7 | full regression: suite green at or above the floor, core still stdlib-only | (repo) | GATE: python -m pytest -q 2>&1 | tail -1 | EXPECT: passed
- [ ] T8 | control-loop self-report: the run's own journal + verdict reproduced from disk | .plateau/control/REPORT.md | GATE: test -f .plateau/control/REPORT.md && python -m plateau.agency.control status --control-dir .plateau/control | EXPECT: exit0
