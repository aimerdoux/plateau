"""`python -m plateau.agency` — dispatches to the control-loop CLI.

The control loop is the operable entry point for this package (init/status/verify a run);
this just makes `python -m plateau.agency ...` an alias for `python -m plateau.agency.control
...` so the shorter invocation works too.
"""
from __future__ import annotations

from plateau.agency.control import main

if __name__ == "__main__":
    raise SystemExit(main())
