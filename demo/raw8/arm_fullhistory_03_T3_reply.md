The code is correct — argparse's `--help` on the `resume` subparser will print output containing "resume" (the subcommand name appears in the usage line), satisfying the gate. I can't execute shell commands in this session to confirm directly, but the implementation follows the existing pattern exactly.

Added a `resume` subcommand to the control CLI in `plateau/agency/control.py`:
- New `p_resume` subparser (`build_parser`) with `--control-dir`, `--root`, and `--json`, matching `verify`/`preflight`'s style.
- Wired into `main()`: calls `resume_plan(args.control_dir, args.root)` and falls through to the existing `_emit(result, args.json)` call.
