Changes look correct and consistent with the existing style.

Added a `resume` subcommand to `plateau/agency/control.py`:
- New `p_resume` argparse subparser (`--control-dir`, `--root`, `--json`), matching the `status`/`preflight` pattern.
- Dispatched in `main()` to call the existing `resume_plan(control_dir, root)` and emit via `_emit`.

`resume_plan` itself already existed (used internally); this just wires it up as a CLI verb, printing its dict (`next`, `gate`, `expect`, `blocked`, `unchecked_count`) in text or `--json` form.
