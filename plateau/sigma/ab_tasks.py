"""plateau.sigma.ab_tasks — the LIVE A/B task set + OBJECTIVE gate checkers.

Each task is a REPRODUCIBLE deliverable: an agent can attempt it FRESH from a clean intent ι
(a self-contained NL spec), and its objective V is DECIDABLE + CHECKABLE on a freshly produced
candidate. Tasks span a SHALLOW -> DEEP depth gradient (depth = count of independent constraints
that must all hold simultaneously / multi-step structure required).

Grounding in the corpus: the operator's transcripts (corpus.py over ~/.claude/projects) yield
deliverables of kind committed_file / sealed_verdict / passing_test / opened_pr. Their AUTO-mined
gates (claim_committed, on-disk-artifact-exists, claim_pr_opened) are NOT checkable on a freshly
produced candidate and are NOT reproducible from a clean intent (per the experiment DESIGN they are
DROPPED). So we keep the corpus's deliverable SHAPES (produce code / structured text / JSON / a
sealed-verdict-style structured artifact satisfying checkable gates) and attach OBJECTIVE
programmatic gates that genuinely check the FRESH output. Every gate body is FIXED CODE registered
by NAME in evaluate's registry (A6: an arm is never scored by a judge it authored; the candidate
string is parsed/executed, never eval'd as a gate body).

A gate checker signature is `(candidate, gate) -> float in [0,1]`; pass iff score >= threshold.
`candidate` is whatever the model arm produced. For the live arms it is a dict
`{"text": <raw claude -p reply>, "code": <extracted code or text>}` produced by the adapter in
ab_run.py. Checkers read candidate["code"] (extracted deliverable) and score it objectively.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

from .evaluate import register_check
from .models import Gate, Verifier


# --------------------------------------------------------------- helpers ----

def _code(candidate) -> str:
    """The deliverable string an arm produced. Adapter hands us {"code","text"}; be liberal."""
    if isinstance(candidate, dict):
        return candidate.get("code") or candidate.get("text") or ""
    if isinstance(candidate, (bytes, str)):
        return candidate.decode() if isinstance(candidate, bytes) else candidate
    return ""


def _run_python(code: str, harness: str, timeout: float = 12.0) -> tuple:
    """Write `code`+`harness` to a temp file, run it in a FRESH subprocess (sandboxed: no
    network use intended, own interpreter), return (ok, stdout, stderr). The harness must
    print 'OBJECTIVE_OK' on success. We never exec candidate code in-process. Objective: the
    candidate either makes the fixed harness assert-pass or it does not — decidable."""
    src = code + "\n\n# ---- objective harness (fixed, not candidate-authored) ----\n" + harness
    fd, path = tempfile.mkstemp(prefix="sigma_ab_", suffix=".py")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(src)
        try:
            p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, "", "TIMEOUT"
        out = p.stdout or ""
        return ("OBJECTIVE_OK" in out), out, (p.stderr or "")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# =============================================================================
#  OBJECTIVE gate checkers — fixed code, registered by name. Score the FRESH candidate.
# =============================================================================

# ---- task 1: palindrome (depth 1) ----
_PALI_HARNESS = r"""
cases = [("A man, a plan, a canal: Panama", True), ("racecar", True),
         ("hello", False), ("", True), ("Was it a car or a cat I saw?", True),
         ("ab", False), ("0P", False), ("Able , was I ere I saw eLba", True)]
ok = True
try:
    for s, want in cases:
        if bool(is_palindrome(s)) != want:
            ok = False
            break
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("ab_palindrome")
def _c_palindrome(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def is_palindrome" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _PALI_HARNESS)
    return 1.0 if ok else 0.0


# ---- task 2: fizzbuzz (depth 1) ----
_FIZZ_HARNESS = r"""
ok = True
try:
    out = fizzbuzz(15)
    want = ["1","2","Fizz","4","Buzz","Fizz","7","8","Fizz","Buzz","11","Fizz","13","14","FizzBuzz"]
    out = [str(x) for x in out]
    ok = (out == want)
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("ab_fizzbuzz")
def _c_fizzbuzz(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def fizzbuzz" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _FIZZ_HARNESS)
    return 1.0 if ok else 0.0


# ---- task 3: json config (depth 2) — structure + types, no code execution ----
@register_check("ab_json_config")
def _c_json_config(candidate, gate):  # noqa: ARG001
    text = _code(candidate)
    # extract first JSON object
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return 0.0
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return 0.0
    if not isinstance(obj, dict):
        return 0.0
    # required keys + types (objective contract)
    checks = [
        ("name", str), ("version", str), ("port", int),
        ("retries", int), ("enabled", bool), ("tags", list),
    ]
    score = 0
    for k, t in checks:
        if k in obj and isinstance(obj[k], t) and not (t is int and isinstance(obj[k], bool)):
            score += 1
    # tags must be a list of >=2 strings; port in 1..65535
    extra = 0
    if isinstance(obj.get("tags"), list) and len(obj["tags"]) >= 2 and \
       all(isinstance(x, str) for x in obj["tags"]):
        extra += 1
    if isinstance(obj.get("port"), int) and not isinstance(obj.get("port"), bool) and \
       1 <= obj["port"] <= 65535:
        extra += 1
    total = score + extra            # max 8
    return 1.0 if total == 8 else 0.0


# ---- task 4: RPN evaluator (depth 3) — parse + arithmetic + error handling ----
_RPN_HARNESS = r"""
ok = True
try:
    assert rpn_eval("3 4 +") == 7
    assert rpn_eval("5 1 2 + 4 * + 3 -") == 14
    assert rpn_eval("2 3 *") == 6
    assert rpn_eval("10 2 /") == 5
    # division error / malformed must raise (not silently return)
    raised = False
    try:
        rpn_eval("1 0 /")
    except Exception:
        raised = True
    assert raised
    raised2 = False
    try:
        rpn_eval("1 +")          # not enough operands
    except Exception:
        raised2 = True
    assert raised2
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("ab_rpn")
def _c_rpn(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def rpn_eval" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _RPN_HARNESS)
    return 1.0 if ok else 0.0


# ---- task 5: markdown table (depth 3) — structured text contract ----
@register_check("ab_md_table")
def _c_md_table(candidate, gate):  # noqa: ARG001
    text = _code(candidate)
    # find a contiguous markdown table block
    lines = [ln.rstrip() for ln in text.splitlines()]
    rows = [ln for ln in lines if ln.strip().startswith("|") and ln.strip().endswith("|")]
    if len(rows) < 5:                # header + sep + >=3 data rows
        return 0.0
    def cells(ln):
        return [c.strip() for c in ln.strip().strip("|").split("|")]
    header = cells(rows[0])
    if len(header) != 3:
        return 0.0
    sep = cells(rows[1])
    if len(sep) != 3 or not all(re.fullmatch(r":?-{3,}:?", s) for s in sep):
        return 0.0
    data = [cells(r) for r in rows[2:]]
    if len(data) < 3 or not all(len(d) == 3 for d in data):
        return 0.0
    # column 3 must be numeric (a "quantity"/"price"-shaped column) — objective
    for d in data:
        if not re.fullmatch(r"-?\d+(\.\d+)?", d[2]):
            return 0.0
    return 1.0


# ---- task 6: ledger parser (depth 4) — parse mini-format, group+sum, edge cases ----
_LEDGER_HARNESS = r"""
ok = True
try:
    sample = "food:12.50\nrent:1000\nfood:7.25\n# a comment\n\ntransport:40\nrent:0\nfood:0.25"
    res = parse_ledger(sample)
    assert isinstance(res, dict)
    assert abs(res["food"] - 20.0) < 1e-6, res
    assert abs(res["rent"] - 1000.0) < 1e-6, res
    assert abs(res["transport"] - 40.0) < 1e-6, res
    # comments and blank lines ignored; no spurious keys
    assert set(res.keys()) == {"food", "rent", "transport"}, res
    # empty input -> empty dict
    assert parse_ledger("") == {}
    # malformed line (no colon) must be skipped, not crash
    assert parse_ledger("garbage\nfood:1") == {"food": 1.0}
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("ab_ledger")
def _c_ledger(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def parse_ledger" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _LEDGER_HARNESS)
    return 1.0 if ok else 0.0


# ---- task 7: turnstile state machine (depth 5) — class + transitions + invariants ----
_FSM_HARNESS = r"""
ok = True
try:
    t = Turnstile()
    assert t.state == "locked"
    # push while locked -> stays locked, denied
    assert t.push() == "denied"
    assert t.state == "locked"
    # coin -> unlocked
    assert t.coin() == "unlocked"
    assert t.state == "unlocked"
    # coin while unlocked -> stays unlocked (extra coin)
    t.coin()
    assert t.state == "unlocked"
    # push while unlocked -> allowed, relocks
    assert t.push() == "allowed"
    assert t.state == "locked"
    # full cycle again
    t.coin(); assert t.state == "unlocked"
    assert t.push() == "allowed"; assert t.state == "locked"
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("ab_fsm")
def _c_fsm(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "class Turnstile" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _FSM_HARNESS)
    return 1.0 if ok else 0.0


# =============================================================================
#  TASK SPECS — clean intent (ι) + objective V (one programmatic gate) + depth rank
# =============================================================================
# The external_anchor for each task is THIS module's path (a real on-disk referent that
# resolves OUTSIDE the loop): the gate body is fixed code living here, re-checkable, and
# neither arm authored it. That is the §3.4 anchor + the A6 guarantee in one.

_ANCHOR = os.path.abspath(__file__)


def _verifier(check_name: str, kpi: str) -> Verifier:
    g = Gate(id=check_name, kpi=kpi, kind="programmatic", check=check_name,
             threshold=1.0, weight=1.0)
    return Verifier(gates=(g,), external_anchor=_ANCHOR)


# Each spec: (task_id, depth, goal-prompt ι, check_name, kpi).
# `goal` is the CLEAN INTENT prompt handed to the model — self-contained, no leaked answer.
TASK_SPECS = [
    dict(
        task_id="t1_palindrome", depth=1, check="ab_palindrome",
        kpi="is_palindrome passes all objective cases (case/punct-insensitive)",
        goal=(
            "Write a Python function `is_palindrome(s)` that returns True if the string `s` is a "
            "palindrome and False otherwise. Ignore case and ignore all non-alphanumeric "
            "characters. The empty string is a palindrome.\n"
            "Output ONLY a single fenced ```python code block containing the function. No prose."
        ),
    ),
    dict(
        task_id="t2_fizzbuzz", depth=1, check="ab_fizzbuzz",
        kpi="fizzbuzz(n) returns exact FizzBuzz sequence 1..n",
        goal=(
            "Write a Python function `fizzbuzz(n)` that returns a list of length n. For each i "
            "from 1 to n: the element is the string \"Fizz\" if i is divisible by 3, \"Buzz\" if "
            "divisible by 5, \"FizzBuzz\" if divisible by both, otherwise the string form of i. "
            "So fizzbuzz(5) == ['1','2','Fizz','4','Buzz'].\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="t3_json_config", depth=2, check="ab_json_config",
        kpi="JSON object with required keys+types (name/version str, port/retries int, "
            "enabled bool, tags list[str]>=2, port in range)",
        goal=(
            "Produce a JSON configuration object (a single JSON object) for a web service with "
            "EXACTLY these keys and types:\n"
            "  - name: string\n  - version: string (semver, e.g. \"1.2.0\")\n"
            "  - port: integer between 1 and 65535\n  - retries: integer\n"
            "  - enabled: boolean\n  - tags: a list of at least 2 strings\n"
            "Output ONLY the JSON object (optionally inside a fenced ```json block). No prose."
        ),
    ),
    dict(
        task_id="t4_rpn", depth=3, check="ab_rpn",
        kpi="rpn_eval evaluates RPN incl. + - * / and RAISES on div-by-zero / underflow",
        goal=(
            "Write a Python function `rpn_eval(expr)` that evaluates a Reverse Polish Notation "
            "expression given as a space-separated string and returns the numeric result. Support "
            "the four operators + - * / on integers. Division should behave such that "
            "rpn_eval(\"10 2 /\") == 5. The function MUST raise an exception (not return a value) "
            "on division by zero and on a malformed expression that has too few operands.\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="t5_md_table", depth=3, check="ab_md_table",
        kpi="valid 3-column GitHub markdown table, header+sep+>=3 rows, col3 numeric",
        goal=(
            "Produce a GitHub-flavored Markdown table with exactly 3 columns: Item, Category, "
            "Quantity. Include a header row, the `|---|---|---|` separator row, and at least 3 "
            "data rows. The Quantity column must contain only numbers.\n"
            "Output ONLY the markdown table. No prose, no code fence."
        ),
    ),
    dict(
        task_id="t6_ledger", depth=4, check="ab_ledger",
        kpi="parse_ledger groups `cat:amount` lines, sums per category, skips comments/blank/"
            "malformed, empty->{}",
        goal=(
            "Write a Python function `parse_ledger(text)` that parses a simple ledger format and "
            "returns a dict mapping category -> total amount (float). The input is newline-"
            "separated. Each valid line is `category:amount` (amount is a number). Sum amounts for "
            "repeated categories. IGNORE blank lines, lines starting with `#` (comments), and any "
            "malformed line that does not contain a colon (skip it, do not crash). Empty input "
            "returns an empty dict. Categories with total 0 still count toward their sum but add "
            "0.\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="t7_fsm", depth=5, check="ab_fsm",
        kpi="Turnstile FSM: locked/unlocked states, coin()/push() transitions + denied/allowed "
            "semantics + relock",
        goal=(
            "Write a Python class `Turnstile` implementing a classic turnstile state machine. "
            "It starts in state \"locked\" (attribute `state`). Methods:\n"
            "  - `coin()`: if locked, transition to \"unlocked\" and return \"unlocked\"; if "
            "already unlocked, stay unlocked and return \"unlocked\".\n"
            "  - `push()`: if unlocked, transition to \"locked\" and return \"allowed\"; if "
            "locked, stay locked and return \"denied\".\n"
            "The `state` attribute must always reflect the current state.\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
]


def task_specs():
    return list(TASK_SPECS)


def verifier_for(spec: dict) -> Verifier:
    return _verifier(spec["check"], spec["kpi"])
