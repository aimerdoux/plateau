"""plateau.sigma.ab_tasks_hard — the HARDER, headroom-bearing A/B task set + OBJECTIVE gates.

Companion to ab_tasks.py. The FLAT N=7 result (RESULTS_AB.md) was a ceiling effect: the base
model one-shot every t1-t7, so the Σ loop had no room to help. This module supplies tasks that
are MEANINGFULLY HARDER — multi-constraint / deep / edge-case-heavy deliverables — so that a
single `claude -p` pass is genuinely at risk of failing the objective gate, giving the WITH arm
measurable HEADROOM to recover into.

Difficulty is OBJECTIVE, never hand-picked to favour the pattern:
  * Each gate is FIXED CODE registered by NAME in evaluate's registry (A6: neither arm authored
    its judge). The candidate string is parsed/executed in a FRESH subprocess sandbox, never
    eval'd as a gate body.
  * Each gate asserts MANY independent properties simultaneously (deep+wide), including
    adversarial edge cases that a hasty single pass tends to miss (overflow, empty input,
    precedence, off-by-one, malformed input, ordering, idempotence, error-vs-return, etc).
  * The headroom is then MEASURED, not assumed: the driver runs ARM_WITHOUT (one pass) on every
    task and records baseline pass/fail. Whether a task actually has headroom is an EMPIRICAL
    outcome, not a property we claimed.

Grounding in the corpus: corpus.py mines deliverables of kind committed_file / passing_test /
sealed_verdict. We keep those SHAPES (produce a Python module that makes a fixed harness assert;
produce a structured JSON artifact satisfying a hard contract; produce a parser/evaluator), but
attach OBJECTIVE programmatic gates that genuinely check the FRESH output. The corpus's own
auto-mined gates (claim_committed, on-disk-existence) are NOT reproducible from a clean intent and
are dropped per the experiment DESIGN, exactly as in ab_tasks.py.
"""

from __future__ import annotations

import json
import os
import re

from .evaluate import register_check
from .models import Gate, Verifier
from .ab_tasks import _code, _run_python   # reuse the same sandboxed subprocess runner + extractor


# =============================================================================
#  OBJECTIVE gate checkers — fixed code, registered by name. Score the FRESH candidate.
#  Every harness asserts MANY independent properties; one miss => FAIL (threshold 1.0).
# =============================================================================

# ---- h1: roman numeral round-trip with strict validation (depth 4) ----
# int->roman AND roman->int, full 1..3999 range, subtractive notation, and STRICT rejection of
# malformed numerals (raise on "IIII", "VV", "IC", out-of-range). Many simultaneous rules.
_ROMAN_HARNESS = r"""
ok = True
try:
    pairs = [(1,"I"),(3,"III"),(4,"IV"),(9,"IX"),(14,"XIV"),(40,"XL"),(90,"XC"),
             (400,"CD"),(900,"CM"),(2024,"MMXXIV"),(3999,"MMMCMXCIX"),(1994,"MCMXCIV"),(58,"LVIII")]
    for n, r in pairs:
        assert to_roman(n) == r, ("to_roman", n, to_roman(n), r)
        assert from_roman(r) == n, ("from_roman", r, from_roman(r), n)
    # round-trip across the whole supported range (sampled)
    for n in [1, 2, 7, 19, 44, 99, 248, 888, 1000, 1666, 2999, 3888, 3999]:
        assert from_roman(to_roman(n)) == n, ("rt", n)
    # out-of-range must RAISE (not clamp / not return junk)
    for bad in [0, -1, 4000, 100000]:
        raised = False
        try:
            to_roman(bad)
        except Exception:
            raised = True
        assert raised, ("to_roman should raise", bad)
    # malformed numerals must RAISE
    for badr in ["IIII", "VV", "IC", "XM", "IL", "ABC", "", "MMMM", "VX"]:
        raised = False
        try:
            from_roman(badr)
        except Exception:
            raised = True
        assert raised, ("from_roman should raise", badr)
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("hard_roman")
def _c_roman(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def to_roman" not in code or "def from_roman" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _ROMAN_HARNESS)
    return 1.0 if ok else 0.0


# ---- h2: shunting-yard infix calculator with precedence + parens + unary minus (depth 5) ----
_CALC_HARNESS = r"""
ok = True
try:
    cases = [
        ("2+3*4", 14), ("(2+3)*4", 20), ("2*3+4", 10), ("10-2-3", 5),
        ("2^3^2", 512),                 # right-assoc exponent
        ("(1+2)*(3+4)", 21), ("100/10/2", 5), ("3+4*2/(1-5)", 1),
        ("-5+3", -2), ("-(2+3)*2", -10), ("2*-3", -6),   # unary minus
        ("  7  +  8 ", 15),             # whitespace tolerance
        ("((((5))))", 5),
    ]
    for expr, want in cases:
        got = calc(expr)
        assert abs(got - want) < 1e-9, (expr, got, want)
    # malformed must RAISE
    for bad in ["2+", "(2+3", "2+3)", "", "+", "2 3", "2**3"]:
        raised = False
        try:
            calc(bad)
        except Exception:
            raised = True
        assert raised, ("should raise", bad)
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("hard_calc")
def _c_calc(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def calc" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _CALC_HARNESS)
    return 1.0 if ok else 0.0


# ---- h3: interval merge + complement (depth 4) — sorting, overlap, touching, complement ----
_INTERVAL_HARNESS = r"""
ok = True
try:
    # merge overlapping/touching, return sorted disjoint list of [start,end]
    assert merge_intervals([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]
    assert merge_intervals([[1,4],[4,5]]) == [[1,5]]          # touching merges
    assert merge_intervals([]) == []
    assert merge_intervals([[5,5]]) == [[5,5]]                 # point interval
    assert merge_intervals([[1,10],[2,3],[4,5]]) == [[1,10]]   # full containment
    assert merge_intervals([[3,4],[1,2]]) == [[1,2],[3,4]]     # unsorted input, NOT touching
    # complement within a bound [lo,hi]
    assert complement([[1,3],[5,7]], 0, 10) == [[0,1],[3,5],[7,10]]
    assert complement([], 0, 5) == [[0,5]]
    assert complement([[0,5]], 0, 5) == []
    assert complement([[2,3]], 0, 10) == [[0,2],[3,10]]
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("hard_intervals")
def _c_intervals(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def merge_intervals" not in code or "def complement" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _INTERVAL_HARNESS)
    return 1.0 if ok else 0.0


# ---- h4: LRU cache class with capacity, eviction, recency on get AND put (depth 5) ----
_LRU_HARNESS = r"""
ok = True
try:
    c = LRUCache(2)
    c.put(1, 1); c.put(2, 2)
    assert c.get(1) == 1            # 1 is now most-recent
    c.put(3, 3)                     # evicts 2 (LRU)
    assert c.get(2) == -1           # 2 evicted
    c.put(4, 4)                     # evicts 1
    assert c.get(1) == -1
    assert c.get(3) == 3
    assert c.get(4) == 4
    # put on existing key updates value AND refreshes recency
    c2 = LRUCache(2)
    c2.put(1, 1); c2.put(2, 2); c2.put(1, 10)   # 1 refreshed
    c2.put(3, 3)                                 # should evict 2, not 1
    assert c2.get(2) == -1
    assert c2.get(1) == 10
    # capacity 1
    c3 = LRUCache(1)
    c3.put(1, 1); c3.put(2, 2)
    assert c3.get(1) == -1 and c3.get(2) == 2
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("hard_lru")
def _c_lru(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "class LRUCache" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _LRU_HARNESS)
    return 1.0 if ok else 0.0


# ---- h5: semver parse + compare incl. prerelease precedence (depth 5) ----
# SemVer 2.0.0 precedence is subtle: prerelease < release; numeric identifiers compared
# numerically; alpha compared lexically; more fields > fewer when all prior equal; build ignored.
_SEMVER_HARNESS = r"""
ok = True
try:
    # compare(a,b) -> -1/0/1
    assert compare("1.0.0", "2.0.0") == -1
    assert compare("2.0.0", "2.1.0") == -1
    assert compare("2.1.0", "2.1.1") == -1
    assert compare("1.0.0", "1.0.0") == 0
    assert compare("1.0.0+build1", "1.0.0+build2") == 0     # build metadata ignored
    # prerelease < release
    assert compare("1.0.0-alpha", "1.0.0") == -1
    assert compare("1.0.0", "1.0.0-alpha") == 1
    # the canonical SemVer precedence chain
    chain = ["1.0.0-alpha","1.0.0-alpha.1","1.0.0-alpha.beta","1.0.0-beta",
             "1.0.0-beta.2","1.0.0-beta.11","1.0.0-rc.1","1.0.0"]
    for i in range(len(chain)-1):
        assert compare(chain[i], chain[i+1]) == -1, (chain[i], chain[i+1])
        assert compare(chain[i+1], chain[i]) == 1
    # numeric vs alphanumeric prerelease identifier
    assert compare("1.0.0-1", "1.0.0-alpha") == -1   # numeric identifiers < alphanumeric
    # invalid versions raise
    for bad in ["1.0", "1", "x.y.z", "", "1.0.0.0", "01.0.0"]:
        raised = False
        try:
            compare(bad, "1.0.0")
        except Exception:
            raised = True
        assert raised, ("should raise", bad)
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("hard_semver")
def _c_semver(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def compare" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _SEMVER_HARNESS)
    return 1.0 if ok else 0.0


# ---- h6: base62 encode/decode round-trip incl. zero + large ints (depth 4) ----
_BASE62_HARNESS = r"""
ok = True
try:
    AL = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    assert encode62(0) == "0"
    assert decode62("0") == 0
    for n in [1, 61, 62, 63, 100, 3844, 999999, 2**32, 2**53, 123456789012345]:
        e = encode62(n)
        assert isinstance(e, str) and e and all(ch in AL for ch in e), (n, e)
        assert decode62(e) == n, (n, e, decode62(e))
        assert e[0] != "0" or n == 0, ("no leading zero unless value 0", n, e)
    # known small encodings
    assert encode62(61) == "z"
    assert encode62(62) == "10"
    # decode rejects out-of-alphabet chars
    for bad in ["!", "1 2", "-", " "]:
        raised = False
        try:
            decode62(bad)
        except Exception:
            raised = True
        assert raised, ("decode should raise", bad)
    # negative encode raises
    raised = False
    try:
        encode62(-1)
    except Exception:
        raised = True
    assert raised
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("hard_base62")
def _c_base62(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def encode62" not in code or "def decode62" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _BASE62_HARNESS)
    return 1.0 if ok else 0.0


# ---- h7: mini JSON-path getter with [] indexing + defaults (depth 4) ----
_JPATH_HARNESS = r"""
ok = True
try:
    data = {"a": {"b": [{"c": 1}, {"c": 2}]}, "x": [10, 20, 30], "n": None, "z": 0}
    assert jget(data, "a.b[0].c") == 1
    assert jget(data, "a.b[1].c") == 2
    assert jget(data, "x[2]") == 30
    assert jget(data, "z") == 0
    assert jget(data, "n") is None
    # missing path returns default (sentinel) rather than raising
    SENT = object()
    assert jget(data, "a.b[5].c", SENT) is SENT
    assert jget(data, "nope", SENT) is SENT
    assert jget(data, "a.q.r", SENT) is SENT
    assert jget(data, "x[9]", SENT) is SENT
    # default defaults to None
    assert jget(data, "missing") is None
    # negative index supported
    assert jget(data, "x[-1]") == 30
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("hard_jsonpath")
def _c_jsonpath(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def jget" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _JPATH_HARNESS)
    return 1.0 if ok else 0.0


# ---- h8: CSV parser with quoted fields, escaped quotes, embedded newlines/commas (depth 5) ----
_CSV_HARNESS = r'''
ok = True
try:
    # RFC-4180-ish: quotes wrap fields; "" is an escaped quote; commas/newlines inside quotes
    src = 'a,b,c\n1,"two, 2","line\nbreak"\n"quote""inside",x,y'
    rows = parse_csv(src)
    assert rows == [["a","b","c"],
                    ["1","two, 2","line\nbreak"],
                    ['quote"inside',"x","y"]], rows
    # trailing newline does not create an empty row
    assert parse_csv("a,b\n1,2\n") == [["a","b"],["1","2"]]
    # empty fields preserved
    assert parse_csv("a,,c") == [["a","","c"]]
    # single field, no comma
    assert parse_csv("hello") == [["hello"]]
    # empty input -> empty list
    assert parse_csv("") == []
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
'''

@register_check("hard_csv")
def _c_csv(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def parse_csv" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _CSV_HARNESS)
    return 1.0 if ok else 0.0


# ---- h9: balanced-bracket validator across 3 bracket kinds + string-literal awareness (depth 4) ----
_BRACKET_HARNESS = r'''
ok = True
try:
    assert is_balanced("()") is True
    assert is_balanced("()[]{}") is True
    assert is_balanced("([{}])") is True
    assert is_balanced("(]") is False
    assert is_balanced("([)]") is False     # interleaved -> invalid
    assert is_balanced("(") is False
    assert is_balanced(")") is False
    assert is_balanced("") is True
    # brackets INSIDE a double-quoted string literal are ignored
    assert is_balanced('("hello]")') is True
    assert is_balanced('("[")') is True
    assert is_balanced('"("') is True       # unmatched paren is inside a string -> balanced
    # escaped quote inside string does not end the string
    assert is_balanced('("a\\"b]")') is True
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
'''

@register_check("hard_brackets")
def _c_brackets(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def is_balanced" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _BRACKET_HARNESS)
    return 1.0 if ok else 0.0


# ---- h10: structured "sealed verdict" JSON artifact with a hard cross-field contract (depth 5) ----
# Mirrors the corpus's sealed_verdict shape: a JSON object whose fields must be internally
# CONSISTENT (not just well-typed). Many simultaneous constraints + a computed checksum-ish rule.
@register_check("hard_verdict_json")
def _c_verdict_json(candidate, gate):  # noqa: ARG001
    text = _code(candidate)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return 0.0
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return 0.0
    if not isinstance(obj, dict):
        return 0.0
    try:
        # 1. required top-level keys + types
        if not (isinstance(obj.get("verdict"), str) and obj["verdict"] in ("PASS", "FAIL")):
            return 0.0
        gates = obj.get("gates")
        if not (isinstance(gates, list) and len(gates) >= 3):
            return 0.0
        for g in gates:
            if not (isinstance(g, dict) and isinstance(g.get("id"), str)
                    and isinstance(g.get("passed"), bool)
                    and isinstance(g.get("score"), (int, float))
                    and not isinstance(g.get("score"), bool)
                    and 0.0 <= float(g["score"]) <= 1.0):
                return 0.0
        # 2. cross-field consistency: passed iff score == 1.0  (objective contract)
        for g in gates:
            if g["passed"] != (float(g["score"]) == 1.0):
                return 0.0
        # 3. summary verdict must equal AND-of-gate-passes
        all_pass = all(g["passed"] for g in gates)
        if obj["verdict"] != ("PASS" if all_pass else "FAIL"):
            return 0.0
        # 4. pass_count must equal the actual number of passing gates
        if not isinstance(obj.get("pass_count"), int) or isinstance(obj.get("pass_count"), bool):
            return 0.0
        if obj["pass_count"] != sum(1 for g in gates if g["passed"]):
            return 0.0
        # 5. gate ids must be unique
        ids = [g["id"] for g in gates]
        if len(ids) != len(set(ids)):
            return 0.0
        # 6. feasibility must equal mean score, rounded to 3 dp (computed contract)
        mean = sum(float(g["score"]) for g in gates) / len(gates)
        feas = obj.get("feasibility")
        if not isinstance(feas, (int, float)) or isinstance(feas, bool):
            return 0.0
        if abs(float(feas) - round(mean, 3)) > 1e-6:
            return 0.0
    except Exception:
        return 0.0
    return 1.0


# ---- h11: topological sort with cycle detection (depth 5) ----
_TOPO_HARNESS = r"""
ok = True
try:
    # returns a valid topological order (list); raises on cycle
    def valid_order(order, edges, nodes):
        if sorted(order) != sorted(nodes):
            return False
        pos = {n: i for i, n in enumerate(order)}
        return all(pos[a] < pos[b] for a, b in edges)
    nodes1 = ["a","b","c","d"]
    edges1 = [("a","b"),("a","c"),("b","d"),("c","d")]
    o1 = toposort(nodes1, edges1)
    assert valid_order(o1, edges1, nodes1), o1
    # no edges -> any permutation of all nodes
    o2 = toposort(["x","y"], [])
    assert sorted(o2) == ["x","y"]
    # single node
    assert toposort(["solo"], []) == ["solo"]
    # cycle MUST raise
    raised = False
    try:
        toposort(["a","b","c"], [("a","b"),("b","c"),("c","a")])
    except Exception:
        raised = True
    assert raised, "cycle should raise"
    # self-loop is a cycle
    raised2 = False
    try:
        toposort(["a"], [("a","a")])
    except Exception:
        raised2 = True
    assert raised2
    # larger DAG
    nodes3 = list("abcdef")
    edges3 = [("a","d"),("f","b"),("b","d"),("f","a"),("d","c")]
    o3 = toposort(nodes3, edges3)
    assert valid_order(o3, edges3, nodes3), o3
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("hard_toposort")
def _c_toposort(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def toposort" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _TOPO_HARNESS)
    return 1.0 if ok else 0.0


# ---- h12: fixed-point decimal money add/round with banker's rounding (depth 5) ----
# Money arithmetic in cents avoiding float error; ROUND_HALF_EVEN (banker's) on division.
_MONEY_HARNESS = r"""
ok = True
try:
    # add(a,b): a,b are decimal strings like "10.99"; returns a normalized "X.XX" string
    assert add("10.99", "0.01") == "11.00"
    assert add("0.10", "0.20") == "0.30"        # the classic float trap
    assert add("-5.00", "5.00") == "0.00"
    assert add("1234567.89", "0.11") == "1234568.00"
    assert add("0.00", "0.00") == "0.00"
    # split(total, n): split total evenly into n parts (strings) summing EXACTLY to total
    parts = split("10.00", 3)
    assert len(parts) == 3
    assert sum(int(p.replace(".","").replace("-","")) for p in parts) == 1000, parts
    # reconstruct: the parts must add back to the total exactly
    acc = "0.00"
    for p in parts:
        acc = add(acc, p)
    assert acc == "10.00", (parts, acc)
    # banker's rounding on round_money(value, places implied 2)
    assert round_money("2.345") == "2.34"   # round half to even -> 2.34
    assert round_money("2.355") == "2.36"   # -> 2.36 (even)
    assert round_money("2.5") == "2.50"
    assert round_money("1.005") == "1.00"   # half to even
except Exception:
    ok = False
print("OBJECTIVE_OK" if ok else "FAIL")
"""

@register_check("hard_money")
def _c_money(candidate, gate):  # noqa: ARG001
    code = _code(candidate)
    if "def add" not in code or "def split" not in code or "def round_money" not in code:
        return 0.0
    ok, _, _ = _run_python(code, _MONEY_HARNESS)
    return 1.0 if ok else 0.0


# =============================================================================
#  TASK SPECS — clean intent (ι) + objective V (one programmatic gate) + depth rank
# =============================================================================

_ANCHOR = os.path.abspath(__file__)


def _verifier(check_name: str, kpi: str) -> Verifier:
    g = Gate(id=check_name, kpi=kpi, kind="programmatic", check=check_name,
             threshold=1.0, weight=1.0)
    return Verifier(gates=(g,), external_anchor=_ANCHOR)


HARD_TASK_SPECS = [
    dict(
        task_id="h1_roman", depth=4, check="hard_roman",
        kpi="to_roman/from_roman round-trip 1..3999, subtractive notation, RAISE on out-of-range "
            "and malformed numerals",
        goal=(
            "Write two Python functions `to_roman(n)` and `from_roman(s)`.\n"
            "- `to_roman(n)`: convert an integer 1..3999 to its standard Roman numeral string "
            "(using subtractive notation: IV, IX, XL, XC, CD, CM). For any n outside 1..3999 it "
            "MUST raise an exception (not clamp, not return junk).\n"
            "- `from_roman(s)`: convert a valid standard Roman numeral string back to its integer. "
            "It MUST raise an exception on any malformed or non-standard numeral (e.g. \"IIII\", "
            "\"VV\", \"IC\", \"MMMM\", empty string).\n"
            "to_roman and from_roman must be exact inverses over 1..3999.\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="h2_calc", depth=5, check="hard_calc",
        kpi="infix calc with +-*/^, correct precedence, right-assoc ^, parens, unary minus, "
            "whitespace; RAISE on malformed",
        goal=(
            "Write a Python function `calc(expr)` that evaluates an arithmetic expression string "
            "and returns the numeric result. Requirements:\n"
            "- Operators: + - * / and ^ (exponent). Standard precedence (^ highest, then * /, then "
            "+ -). ^ is RIGHT-associative, so calc(\"2^3^2\") == 512.\n"
            "- Parentheses for grouping, arbitrarily nested.\n"
            "- Unary minus, e.g. calc(\"-5+3\") == -2 and calc(\"2*-3\") == -6.\n"
            "- Tolerate arbitrary surrounding/internal whitespace.\n"
            "- Raise an exception on any malformed expression (unbalanced parens, trailing "
            "operator, empty input, two adjacent numbers).\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="h3_intervals", depth=4, check="hard_intervals",
        kpi="merge_intervals (overlap+touching+containment+unsorted) and complement within bound",
        goal=(
            "Write two Python functions operating on integer intervals represented as [start, end] "
            "lists.\n"
            "- `merge_intervals(intervals)`: merge all overlapping OR touching intervals (e.g. "
            "[1,4] and [4,5] merge to [1,5]) and return them sorted by start as a list of "
            "[start,end] lists. Handle unsorted input, full containment, point intervals [x,x], "
            "and the empty list.\n"
            "- `complement(intervals, lo, hi)`: given a (possibly unsorted/overlapping) set of "
            "intervals and a bounding range [lo, hi], return the sorted list of gaps within "
            "[lo, hi] NOT covered by any interval, as [start,end] lists.\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="h4_lru", depth=5, check="hard_lru",
        kpi="LRUCache(cap) with get/put, eviction of true-LRU, recency refresh on BOTH get and put",
        goal=(
            "Write a Python class `LRUCache` implementing a least-recently-used cache.\n"
            "- `LRUCache(capacity)`: fixed positive capacity.\n"
            "- `get(key)`: return the value, or -1 if absent. A successful get marks the key as "
            "most-recently-used.\n"
            "- `put(key, value)`: insert/update. Updating an existing key refreshes its recency "
            "AND its value. When inserting a new key would exceed capacity, evict the "
            "least-recently-used key first.\n"
            "Recency must be updated on BOTH get and put.\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="h5_semver", depth=5, check="hard_semver",
        kpi="SemVer 2.0.0 compare(a,b)->-1/0/1: prerelease precedence, numeric vs alpha ids, build "
            "ignored, RAISE on invalid",
        goal=(
            "Write a Python function `compare(a, b)` that compares two SemVer 2.0.0 version strings "
            "and returns -1 if a<b, 0 if equal, 1 if a>b, using full SemVer precedence rules:\n"
            "- Compare major, minor, patch numerically.\n"
            "- A version WITH a prerelease has LOWER precedence than the same version without one "
            "(1.0.0-alpha < 1.0.0).\n"
            "- Prerelease identifiers are compared left-to-right: numeric identifiers compared "
            "numerically, alphanumeric compared lexically (ASCII), numeric < alphanumeric, and a "
            "larger set of identifiers wins when all preceding are equal "
            "(1.0.0-alpha < 1.0.0-alpha.1).\n"
            "- Build metadata (after '+') is IGNORED in precedence.\n"
            "- Raise an exception on any invalid version (missing a component, leading zeros, "
            "non-numeric core, empty).\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="h6_base62", depth=4, check="hard_base62",
        kpi="encode62/decode62 round-trip incl. 0 and large ints, no leading zero, RAISE on "
            "negative / bad chars",
        goal=(
            "Write two Python functions for base62 using the alphabet "
            "\"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz\" (digits, then "
            "uppercase, then lowercase).\n"
            "- `encode62(n)`: encode a non-negative integer to a base62 string. encode62(0) == "
            "\"0\". No leading zeros for n>0 (so encode62(62) == \"10\"). Raise on negative n.\n"
            "- `decode62(s)`: decode a base62 string back to an integer. Raise on any character "
            "outside the alphabet.\n"
            "encode62 and decode62 must be exact inverses for all non-negative integers, including "
            "very large ones.\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="h7_jsonpath", depth=4, check="hard_jsonpath",
        kpi="jget(obj,path,default) dotted keys + [i] indexing + negative index + default on miss",
        goal=(
            "Write a Python function `jget(obj, path, default=None)` that reads a value out of a "
            "nested dict/list structure using a dotted path with bracket indexing.\n"
            "- Dotted keys traverse dict keys: \"a.b.c\".\n"
            "- Bracket indices traverse lists: \"x[2]\", and combined: \"a.b[0].c\".\n"
            "- Negative list indices are supported: \"x[-1]\".\n"
            "- If ANY step of the path is missing (missing key, index out of range, wrong type), "
            "return `default` (which itself defaults to None) instead of raising.\n"
            "- A present value that is None or 0 must be returned as-is (do not confuse with "
            "missing).\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="h8_csv", depth=5, check="hard_csv",
        kpi="parse_csv RFC-4180-ish: quoted fields, escaped \"\" quotes, embedded commas+newlines, "
            "empty fields, trailing newline",
        goal=(
            "Write a Python function `parse_csv(text)` that parses CSV text into a list of rows "
            "(each row a list of string fields), following RFC-4180-style rules:\n"
            "- Fields are comma-separated, rows are newline-separated.\n"
            "- A field may be wrapped in double quotes; inside a quoted field, a comma and a "
            "newline are literal (part of the field).\n"
            "- Inside a quoted field, two double quotes (\"\") represent one literal double "
            "quote.\n"
            "- Empty fields are preserved (\"a,,c\" -> [\"a\",\"\",\"c\"]).\n"
            "- A trailing newline at the very end does NOT create an extra empty row.\n"
            "- Empty input returns an empty list.\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="h9_brackets", depth=4, check="hard_brackets",
        kpi="is_balanced 3 bracket kinds, reject interleaving, ignore brackets inside double-quoted "
            "string literals incl. escaped quote",
        goal=(
            "Write a Python function `is_balanced(s)` that returns True iff the brackets in `s` are "
            "balanced and correctly nested.\n"
            "- Three bracket kinds: () [] {}. A closing bracket must match the most recent unmatched "
            "opening bracket of the same kind; interleaving like \"([)]\" is NOT balanced.\n"
            "- Brackets that appear INSIDE a double-quoted string literal are ignored (not counted). "
            "A double-quoted string starts at a \" and ends at the next unescaped \".\n"
            "- A backslash-escaped quote (\\\") inside a string does NOT end the string.\n"
            "- The empty string is balanced.\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="h10_verdict_json", depth=5, check="hard_verdict_json",
        kpi="sealed-verdict JSON with cross-field consistency: passed==(score==1), verdict==AND, "
            "pass_count, unique ids, feasibility==mean(score) rounded 3dp",
        goal=(
            "Produce a single JSON object representing a sealed verdict over a set of gates, with "
            "these fields and INTERNALLY CONSISTENT values:\n"
            "  - gates: a list of at least 3 objects, each {\"id\": string (unique across gates), "
            "\"passed\": boolean, \"score\": number in [0,1]}. For each gate, `passed` must be true "
            "if and only if `score` == 1.0.\n"
            "  - pass_count: integer equal to the number of gates whose passed is true.\n"
            "  - feasibility: the mean of all gate scores, rounded to exactly 3 decimal places.\n"
            "  - verdict: the string \"PASS\" if ALL gates passed, otherwise \"FAIL\".\n"
            "Make the object internally consistent (the computed fields must match the gates you "
            "list). Include at least one failing gate so verdict is \"FAIL\".\n"
            "Output ONLY the JSON object (optionally inside a fenced ```json block). No prose."
        ),
    ),
    dict(
        task_id="h11_toposort", depth=5, check="hard_toposort",
        kpi="toposort(nodes,edges) valid topological order over all nodes; RAISE on any cycle incl. "
            "self-loop",
        goal=(
            "Write a Python function `toposort(nodes, edges)` that returns a valid topological "
            "ordering of `nodes` (a list) given `edges` (a list of (a, b) pairs meaning a must come "
            "before b).\n"
            "- The returned list must contain every node exactly once, with every edge respected "
            "(a appears before b).\n"
            "- If the graph contains ANY cycle (including a self-loop a->a), raise an exception.\n"
            "- Nodes with no edges may appear in any position.\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
    dict(
        task_id="h12_money", depth=5, check="hard_money",
        kpi="exact decimal money: add(a,b) no float error, split(total,n) sums exactly, "
            "round_money banker's rounding to 2dp",
        goal=(
            "Write three Python functions for exact 2-decimal money handling (avoid binary float "
            "error; compute in integer cents or use the decimal module).\n"
            "- `add(a, b)`: a and b are decimal strings like \"10.99\" or \"-5.00\"; return their "
            "sum as a normalized string with exactly 2 decimals (e.g. add(\"0.10\",\"0.20\") == "
            "\"0.30\").\n"
            "- `split(total, n)`: split the money string `total` into `n` parts (list of strings) "
            "that sum EXACTLY back to total, distributing any leftover cent(s) so no money is lost.\n"
            "- `round_money(value)`: round a decimal string to 2 decimals using BANKER'S rounding "
            "(round half to even), returning a normalized \"X.XX\" string (round_money(\"2.345\") "
            "== \"2.34\", round_money(\"2.355\") == \"2.36\").\n"
            "Output ONLY a single fenced ```python code block. No prose."
        ),
    ),
]


def hard_task_specs():
    return list(HARD_TASK_SPECS)


def verifier_for(spec: dict) -> Verifier:
    return _verifier(spec["check"], spec["kpi"])
