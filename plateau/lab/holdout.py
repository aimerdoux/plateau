"""plateau.lab.holdout — deterministic holdout assignment for bridge injections.

A given (session, compaction) is deterministically assigned to the holdout arm so the
lab can measure recall WITHOUT the bridge on a controlled fraction of compactions,
without needing a second live session to run as a control. Same session_id and k always
give the same answer (needed so a retried/duplicated SessionStart doesn't flip arms).
"""

from __future__ import annotations

import hashlib


def is_holdout(session_id: str, k: int, rate: float) -> bool:
    """True if (session_id, k) falls in the holdout bucket at the given rate (0..1)."""
    digest = hashlib.sha256(f"{session_id}:{k}".encode("utf-8")).hexdigest()
    return int(digest, 16) % 100 < int(round(rate * 100))
