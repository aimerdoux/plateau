"""Deprecated shim: moved to plateau.bridge.common; kept so the sealed D-037/D-038 instruments run unchanged."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["PLATEAU_DB_REL"] = ".d037/index.sqlite"
os.environ["PLATEAU_LOG_REL"] = ".d037/hooks.log"
os.environ["PLATEAU_LEGACY_TAG"] = "1"

from plateau.bridge.common import *  # noqa: F401,F403
