#!/usr/bin/env python3
"""Deprecated shim: moved to plateau.bridge.lookup; kept so the sealed D-037/D-038 instruments run unchanged."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["PLATEAU_DB_REL"] = ".d037/index.sqlite"
os.environ["PLATEAU_LOG_REL"] = ".d037/hooks.log"
os.environ["PLATEAU_LEGACY_TAG"] = "1"

from plateau.bridge.lookup import main

if __name__ == "__main__":
    main()
