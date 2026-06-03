"""Bounded RelationalState (the signal) + tiered backlog (coverage).

Disk-backed, stdlib only. The driver process holds *only* what these helpers
return; nothing here grows unbounded. Caps are enforced on every save.
"""
import hashlib
import json
from pathlib import Path

# --- signal caps (faithful to the spec) ---
LESSON_MAX = 12
LESSON_CHARS = 140
LESSON_TOTAL_BYTES = 1536  # 1.5 KB
GOAL_CHARS = 120

TIERS = {1: "sec", 2: "core", 3: "ux", 4: "hardening"}


def sha256_file(path):
    """sha256:<hex> for a file's current bytes, or None if missing."""
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text())


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2))


# ---------------------------------------------------------------- signal ----

def new_signal(run_id, run_start):
    return {
        "run_id": run_id,
        "run_start": run_start,
        "resume_count": 0,
        "stance": "fresh run; drain tier-1 SEC before anything lower",
        "open_goals": [],          # [{id, tier, text}]
        "lessons": [],             # [str], capped
        "pointers": {},            # paths/ids only, never file bodies
        "verified_facts": [],      # gated facts for the CURRENTLY-OPEN item only
    }


def enforce_caps(sig):
    """Hard-truncate + evict so the signal can never bloat the driver."""
    lessons = [l[:LESSON_CHARS] for l in sig.get("lessons", [])]
    while len(lessons) > LESSON_MAX:
        lessons.pop(0)
    while len(lessons) > 1 and sum(len(l.encode()) for l in lessons) > LESSON_TOTAL_BYTES:
        lessons.pop(0)
    sig["lessons"] = lessons
    for g in sig.get("open_goals", []):
        g["text"] = g.get("text", "")[:GOAL_CHARS]
    return sig


def add_lesson(sig, text):
    if text:
        sig.setdefault("lessons", []).append(str(text)[:LESSON_CHARS])
    return enforce_caps(sig)


def set_open_item_facts(sig, facts):
    """verified_facts holds ONLY the open item's gated facts; closed-item
    facts live in the ledger, never in the signal."""
    sig["verified_facts"] = facts
    return sig


def compact_signal(sig, max_bytes=4000):
    """The small blob actually rendered into a fresh agent's prompt."""
    view = {
        "stance": sig.get("stance", ""),
        "open_goals": sig.get("open_goals", []),
        "lessons": sig.get("lessons", []),
        "pointers": sig.get("pointers", {}),
        "verified_facts": sig.get("verified_facts", []),
    }
    blob = json.dumps(view, indent=2)
    return blob[:max_bytes]


# -------------------------------------------------------------- coverage ----

def cov_counts(coverage):
    """{status: n} and per-tier {covered,total} without holding the list."""
    by_status = {}
    by_tier = {name: {"covered": 0, "total": 0} for name in TIERS.values()}
    for e in coverage:
        by_status[e["status"]] = by_status.get(e["status"], 0) + 1
        tname = TIERS.get(e["tier"], "hardening")
        by_tier[tname]["total"] += 1
        if e["status"] == "covered":
            by_tier[tname]["covered"] += 1
    return by_status, by_tier


def next_pending(coverage):
    """Strict ascending-tier pick. Returns the entry dict or None.

    Enforces the tier-gate invariant implicitly: a lower tier is never
    returned while a higher (lower-number) tier still has pending/in_progress.
    """
    open_tiers = sorted({
        e["tier"] for e in coverage if e["status"] in ("pending", "in_progress")
    })
    if not open_tiers:
        return None
    top = open_tiers[0]
    for e in coverage:
        if e["tier"] == top and e["status"] == "pending":
            return e
    return None  # top tier only has in_progress -> caller waits/handles


def find_entry(coverage, item_id):
    for e in coverage:
        if e["id"] == item_id:
            return e
    return None


def pattern_seen(ledger_path, pattern_key):
    """Dedupe: has this normalized claim+component already been gated/found?
    Reads the ledger by streaming lines, never holding the whole file."""
    if not pattern_key or not Path(ledger_path).exists():
        return False
    with open(ledger_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("pattern_key") == pattern_key and rec.get("outcome") in (
                "gated", "trivial", "found"
            ):
                return True
    return False
