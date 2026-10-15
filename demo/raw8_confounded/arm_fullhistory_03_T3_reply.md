I can't run the gate myself, but the change is straightforward and mirrors the existing subcommand pattern.

Added a `resume` subcommand to the control CLI (`plateau/agency/control.py`): registered in `build_parser` with `--control-dir`, `--root`, and `--json` (matching `verify`'s style), and wired in `main()` to call `resume_plan(args.control_dir, args.root)` and emit via the existing `_emit` helper.
