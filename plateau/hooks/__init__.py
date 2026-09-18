"""plateau.hooks — the package-owned home of Plateau's Claude-Code hook logic.

`plateau.hooks.signal` holds `parent`/`pre`/`post` (docs/harness-0.3/PLAN-step4.md
"S4-A1 One install story"): moved here from `adapters/claude_code/hook.py`, which is now
a thin shim that dispatches every mode into this package (or into `plateau.bridge`/
`plateau.lab` for the step-3 modes). `plateau hook <mode>` (see `plateau.cli`) dispatches
here too, so the two entry points — the plugin file and the console script — share one
implementation.
"""

from __future__ import annotations
