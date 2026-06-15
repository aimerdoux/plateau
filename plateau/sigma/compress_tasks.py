"""plateau.sigma.compress_tasks — SELECT + BUILD the REAL compression/decompression tasks.

The §4-valuation / A1-round-trip test of the Σ thesis on the operator's OWN sessions:

  A real deliverable D originally took a full MULTI-TURN session (discovery, false starts).
  extract_schema compresses that trajectory -> a short Σ schema. QUESTION: can a FRESH single
  `claude -p` pass prompted with ONLY the Σ schema reproduce a deliverable that passes the
  ORIGINAL's objective V — i.e. one-shot what originally took N turns?

This module is DATA-ONLY (it never executes transcript content). It:
  1. mines ~/.claude/projects/**/*.jsonl for sessions whose deliverable is a SELF-CONTAINED
     python package D with a companion TEST file T that imports D and asserts >=2 real
     correctness properties — T is the OBJECTIVE V (authored in-session, by NEITHER arm);
  2. requires the session was genuinely MULTI-TURN (>=3 real user prompts) — real headroom;
  3. requires D reproducible-in-principle (stdlib-only impl imports — no numpy/pydantic/repo
     coupling / no environment-bound deliverable) — drops the rest;
  4. derives THREE artifacts per task:
       - iota_naive : the raw turn-1 user ask (COLD baseline) — feature list, no accreted depth.
       - sigma_schema : distilled clean intent + target_invariants + constraints + excluded_paths
                        + Phi fossils. The CONTRACT (module/symbol/key/flag names + semantics) is
                        derived from the TEST file (= V), NOT from D — so the schema carries the
                        RECIPE, never the dish.
       - objective_V : the original test suite source + the impl module layout it requires.
  5. LEAKAGE GUARD: verifies sigma_schema does NOT contain impl D verbatim/near-verbatim
     (normalized-substring containment + high token/line overlap); DROPS any task that leaks.

NO FABRICATION: every byte of D, T, and the turn-1 ask is lifted verbatim (redacted) from the
real transcript. The schema's contract is lifted from T (the real spec), not invented.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

from .corpus import iter_transcripts, parse_session

# stdlib modules an impl may import and still be "reproducible-in-principle" in a bare subprocess.
_STDLIB = set("""
__future__ argparse csv datetime json pathlib sys os io contextlib tempfile shutil typing
dataclasses decimal collections math re functools itertools enum abc unittest hashlib time
random string textwrap copy uuid base64 subprocess calendar bisect heapq operator warnings
glob fnmatch stat statistics difflib pprint dataclass
""".split())


@dataclass
class CompressTask:
    task_id: str
    session_file: str
    session_hash: str
    n_turns: int
    n_prompts: int
    pkg: str                              # the python package name the test imports (e.g. "spend")
    test_name: str                        # basename of the test file (the objective V)
    test_src: str                         # full test source (the objective V) — redacted
    impl_files: dict = field(default_factory=dict)   # {relpath: source} — the deliverable D
    iota_naive: str = ""                  # COLD: raw turn-1 ask
    n_asserts: int = 0
    n_tests: int = 0
    # filled by build_sigma_schema:
    sigma_schema: str = ""
    leak_ratio: float = 0.0
    leak_substr: bool = False


# ----------------------------------------------------------- transcript reconstruct ----

def _reconstruct_writes(turns) -> dict:
    """Final full-Write content per path (last Write wins). Edits can't be reconstructed; a path
    whose terminal op is Edit is still returned at its last Write content (best-effort, flagged
    by the self-containment + import checks downstream). DATA only."""
    content = {}
    for t in turns:
        for tu in t.tool_uses:
            if tu.get("name") == "Write":
                inp = tu.get("input", {}) or {}
                fp = inp.get("file_path") or inp.get("path")
                if fp:
                    content[fp] = inp.get("content", "")
    return content


def _imports(src: str) -> set:
    return set(re.findall(r"^\s*(?:from|import)\s+([a-zA-Z_][\w]*)", src, re.M))


def _user_prompts(turns) -> list:
    """Real user prompts: text rows that are not tool_results and not slash-command plumbing."""
    out = []
    for t in turns:
        if t.role != "user" or not t.text or t.tool_results:
            continue
        txt = t.text.strip()
        if not txt or len(txt) < 8:
            continue
        out.append(txt)
    return out


def _clean_first_ask(prompts: list) -> str:
    """The COLD turn-1 ask. Strip the local-command-caveat envelope and slash-command plumbing;
    pick the first substantive natural-language ask. Verbatim (redacted) — NOT invented."""
    for p in prompts:
        s = p
        # drop the caveat envelope if present
        s = re.sub(r"<local-command-[^>]*>.*?</local-command-[^>]*>", "", s, flags=re.S)
        s = re.sub(r"<command-[^>]*>.*?</command-[^>]*>", "", s, flags=re.S)
        s = s.strip()
        # skip pure slash-command / plumbing turns
        if not s or s.startswith("/") or s.lower() in ("go", "go /loop", "installed", "continue"):
            continue
        if len(s) >= 40:
            return s
    return prompts[0] if prompts else ""


# ---------------------------------------------------------------- selection ----

def _existing_py_targets(turns) -> set:
    """Every .py path the session Wrote/Edited that STILL EXISTS on disk — the ground-truth D.

    On-disk content is the faithful deliverable (it reflects every Edit, no redaction corruption),
    unlike transcript-Write reconstruction. We only build tasks from files that exist, so the
    deliverable we ask the arms to reproduce is real and the objective V is runnable."""
    out = set()
    for t in turns:
        for tu in t.tool_uses:
            if tu.get("name") in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                inp = tu.get("input", {}) or {}
                fp = inp.get("file_path") or inp.get("path")
                if isinstance(fp, str) and fp.endswith(".py") and os.path.isfile(fp):
                    out.add(fp)
    return out


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def select_tasks(min_prompts: int = 3, min_turns: int = 10, min_asserts: int = 2,
                 root: Optional[str] = None) -> list:
    """Scan the corpus; return CompressTask rows anchored to ON-DISK ground-truth deliverables.

    Objective criteria only (NOT hand-picked to favor Σ):
      - >= min_prompts real user prompts AND >= min_turns turns (genuinely multi-turn).
      - the session produced a test file (still on disk) that imports an impl module/package
        also still on disk, asserting >= min_asserts properties (the OBJECTIVE V).
      - the impl set imports ONLY stdlib + sibling modules (reproducible-in-principle); any
        third-party / cross-repo import -> DROP (environment-bound, not reproducible).
    Deliverable D and test V are read VERBATIM from disk (faithful; includes all edits).
    Returns tasks sorted by (#asserts desc) so the substantive Vs come first.
    """
    tasks: list = []
    seen_ids = set()
    it = iter_transcripts(root) if root else iter_transcripts()
    for path in it:
        turns = parse_session(path)
        if len(turns) < min_turns:
            continue
        prompts = _user_prompts(turns)
        if len(prompts) < min_prompts:
            continue
        pyset = _existing_py_targets(turns)
        if not pyset:
            continue
        pys = {f: _read(f) for f in pyset}
        tests = {f: src for f, src in pys.items()
                 if re.search(r"(^|/)test", os.path.basename(f).lower())
                 and ("def test_" in src or src.count("assert") >= min_asserts)}
        impls = {f: src for f, src in pys.items() if f not in tests}
        if not tests or not impls:
            continue
        mod_by_name = {os.path.splitext(os.path.basename(f))[0]: f for f in impls}
        pkg_dirs = {os.path.basename(os.path.dirname(f)) for f in impls}
        for tf, tsrc in tests.items():
            timp = _imports(tsrc)
            local = [m for m in timp if m in mod_by_name or m in pkg_dirs]
            if not local:
                continue
            # the impl set lives in the package dir(s) the test imports.
            target_pkgs = {os.path.dirname(mod_by_name[m]) for m in timp if m in mod_by_name}
            target_pkgs |= {os.path.dirname(f) for f in impls
                            if os.path.basename(os.path.dirname(f)) in timp}
            impl_set = {f: src for f, src in impls.items()
                        if os.path.dirname(f) in target_pkgs} or dict(impls)
            own = set(mod_by_name) | pkg_dirs
            ext = set()
            for src in impl_set.values():
                ext |= (_imports(src) - _STDLIB - own)
            if ext:
                continue   # external dep / repo coupling -> NOT reproducible-in-principle -> DROP
            n_asserts = tsrc.count("assert")
            n_tests = tsrc.count("def test_")
            if n_asserts < min_asserts and n_tests < 1:
                continue
            # determine the import root + package name from how the test imports it.
            # bare `from todo import ...` -> pkg "todo", file at root (todo.py).
            # `from xpense import model` -> pkg "xpense", files under xpense/.
            pkg_name = local[0]
            # importable parent: the dir that must be on sys.path for `import pkg_name` to work.
            sample = next(iter(impl_set))
            sample_base = os.path.splitext(os.path.basename(sample))[0]
            if pkg_name in pkg_dirs:                 # package import: parent of the package dir
                pkg_dir = next(d for d in target_pkgs if os.path.basename(d) == pkg_name) \
                    if any(os.path.basename(d) == pkg_name for d in target_pkgs) \
                    else os.path.dirname(sample)
                import_root = os.path.dirname(pkg_dir)
            else:                                    # bare module import: dir containing the module
                import_root = os.path.dirname(mod_by_name.get(pkg_name, sample))
            rel_impl = {}
            for f, src in impl_set.items():
                rel = os.path.relpath(f, import_root)
                rel_impl[rel] = src
            sess_hash_short = os.path.splitext(os.path.basename(path))[0][:12]
            tid = f"{sess_hash_short}__{os.path.splitext(os.path.basename(tf))[0]}"
            if tid in seen_ids:
                continue
            seen_ids.add(tid)
            tasks.append(CompressTask(
                task_id=tid,
                session_file=os.path.basename(path),
                session_hash="",
                n_turns=len(turns),
                n_prompts=len(prompts),
                pkg=pkg_name,
                test_name=os.path.basename(tf),
                test_src=tsrc,
                impl_files=rel_impl,
                iota_naive=_clean_first_ask(prompts),
                n_asserts=n_asserts,
                n_tests=n_tests,
            ))
    tasks.sort(key=lambda t: (-t.n_asserts, -t.n_prompts))
    return tasks


# ---------------------------------------------------- Σ schema synthesis (the RECIPE) ----
# The schema carries the CONTRACT + paid decisions, NEVER impl bodies. The contract is derived
# from the TEST file (= V), not from D — so by construction the recipe is not the dish.

_DEF_RE = re.compile(r"\b([a-zA-Z_]\w*)\.([a-zA-Z_]\w*)\s*\(")          # module.symbol(
_ATTR_RE = re.compile(r"\[(?:'|\")([a-zA-Z_]\w*)(?:'|\")\]")             # dict["key"]
_CONST_RE = re.compile(r"\b([a-z_]+)\.([A-Z][A-Z0-9_]+)\b")             # module.CONST
_CLIFLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]+|-[a-z])(?![\w-])")


def _contract_from_test(task: CompressTask) -> dict:
    """Extract the API/behavioral CONTRACT the objective V requires, FROM THE TEST (not from D).

    These are 'what V checks' — module symbols called, dict keys asserted, constants referenced,
    and CLI flags exercised. Carrying them in the schema is legitimate compression (the recipe);
    none of it is an impl body."""
    t = task.test_src
    # the modules that ARE the deliverable (so we keep only contract symbols on the package's
    # own modules, not on stdlib test-harness helpers like contextlib/tempfile/buf/path/self).
    own_mods = {os.path.splitext(os.path.basename(p))[0] for p in task.impl_files} | {task.pkg}
    _HARNESS = {"self", "os", "json", "io", "unittest", "contextlib", "tempfile", "shutil",
                "buf", "path", "f", "environ", "sys", "subprocess", "p", "datetime", "csv",
                "Path", "open"}
    symbols = sorted({f"{m}.{s}" for m, s in _DEF_RE.findall(t)
                      if m in own_mods and m not in _HARNESS})
    keys = sorted({k for k in set(_ATTR_RE.findall(t))
                   if len(k) >= 2 and k not in ("am", "t")})   # drop 1-char/value-literal noise
    consts = sorted({f"{m}.{c}" for m, c in _CONST_RE.findall(t) if m in own_mods})
    flags = sorted(set(_CLIFLAG_RE.findall(t)))
    return {"symbols": symbols, "keys": keys, "consts": consts, "flags": flags}


def _decisions_from_trajectory(task: CompressTask) -> dict:
    """Mine the trajectory for the architectural DECISIONS that emerged (Φ fossils) and the
    false starts (excluded_paths). DATA-only; quotes the operator's own prompts.

    Φ-fossil sources (paid sub-results, not the dish): the load-bearing decisions the original
    build pinned down — surfaced from the test's observable semantics + the build plan."""
    iota = task.iota_naive
    # excluded paths: numbered build-plan constraints of the form "must X without breaking Y"
    excluded = []
    for m in re.findall(r"must ([a-z][^\n.]+? without [^\n.)]+)", iota, flags=re.I):
        phrase = re.sub(r"\s+", " ", m.strip()).rstrip(") ")
        # phrase reads e.g. "extend the turn-1 schema without breaking turn-4 persistence"
        excluded.append(f"you MUST {phrase} (a naive rewrite that ignores this is a dead end)")
    # Φ fossils: paid sub-results phrased as decisions, derived from V's observable semantics.
    fossils = []
    # money-in-integer-cents (a classic load-bearing decision the suite encodes)
    if re.search(r"parse_amount|amount_cents|format_amount|cents", task.test_src):
        fossils.append("money is stored as INTEGER minor units (cents), never float; "
                       "parse '$1,234.5' -> 123450 and format 123450 -> '1234.50'.")
    if re.search(r"SCHEMA_VERSION|version.*1.*2|migrate", task.test_src, re.I):
        fossils.append("the store is schema-VERSIONED; an old (v1) file must auto-migrate to the "
                       "current version on load, preserving the original entries.")
    if re.search(r"next_id|stable.*id|ids? climb|\[1, 2\]", task.test_src):
        fossils.append("entries carry stable monotonic integer ids from a persisted next_id "
                       "counter (ids climb 1,2,3 and survive reload).")
    if re.search(r"tags.*fresh|shared mutable|append.*tags", task.test_src, re.I):
        fossils.append("per-entry tags default to a FRESH list (no shared-mutable-default bug).")
    if re.search(r"undo", task.test_src, re.I):
        fossils.append("a single-level UNDO restores the prior state of the last mutation.")
    if re.search(r"_FILE|_CONFIG|environ|env over", task.test_src):
        fossils.append("data + config file locations are overridable via environment variables "
                       "so tests can redirect them to a temp dir.")
    return {"excluded": excluded, "fossils": fossils}


def build_sigma_schema(task: CompressTask) -> str:
    """Author the Σ_SCHEMA prompt: clean intent + target_invariants + constraints + excluded_paths
    + Φ fossils + the V-derived contract + the required module layout. NEVER includes impl bodies.

    This is the COMPRESSED RECIPE a fresh single pass is handed in ARM_SIGMA."""
    contract = _contract_from_test(task)
    dec = _decisions_from_trajectory(task)
    layout = sorted(task.impl_files.keys())

    goal = ("Reproduce a self-contained Python package that was originally built over a multi-turn "
            f"session. The package is imported as `{task.pkg}`. Your output will be checked by an "
            "objective test suite (authored by neither you nor any baseline) that imports your "
            "package and asserts its behavior — you must satisfy ALL of it in ONE shot.")

    lines = []
    lines.append("# Σ SCHEMA — compressed recipe for a multi-turn deliverable")
    lines.append("")
    lines.append("## ι — Clean intent")
    lines.append(goal)
    lines.append("")
    lines.append("## Target invariants (what makes this THE deliverable — the V-derived contract)")
    lines.append(f"- Package name (import root): `{task.pkg}`")
    if layout:
        lines.append("- Required module files (create EXACTLY these, package-relative):")
        for f in layout:
            lines.append(f"    - {f}")
    if contract["symbols"]:
        lines.append("- Public callables the suite invokes (module.symbol — must exist with "
                     "compatible signatures):")
        lines.append("    " + ", ".join(contract["symbols"]))
    if contract["consts"]:
        lines.append("- Module constants the suite reads: " + ", ".join(contract["consts"]))
    if contract["keys"]:
        lines.append("- Record/dict keys the suite asserts on (use these EXACT names): "
                     + ", ".join(f"`{k}`" for k in contract["keys"]))
    if contract["flags"]:
        lines.append("- CLI flags/options the suite exercises (support these EXACTLY): "
                     + ", ".join(f"`{fl}`" for fl in contract["flags"]))
    lines.append("")
    lines.append("## Constraints")
    lines.append("- Standard library only — no third-party packages.")
    lines.append("- Output the COMPLETE package: one fenced ```python block PER FILE, each "
                 "immediately preceded by a line `# FILE: <relative/path>` so the files can be "
                 "written verbatim.")
    lines.append("- The package must import cleanly and the suite must pass with zero failures.")
    if dec["fossils"]:
        lines.append("")
        lines.append("## Φ — Paid sub-results (load-bearing decisions the original build pinned "
                     "down; reuse them, do not re-derive):")
        for fo in dec["fossils"]:
            lines.append(f"- {fo}")
    if dec["excluded"]:
        lines.append("")
        lines.append("## Excluded paths (proven dead — do NOT take these):")
        for ex in dec["excluded"]:
            lines.append(f"- {ex}")
    lines.append("")
    lines.append("## γ — One shot")
    lines.append("Produce the full package now, in one response. No questions, no commentary "
                 "outside the fenced file blocks.")
    return "\n".join(lines)


# ------------------------------------------------------------------ leakage guard ----

def _norm(s: str) -> str:
    """Normalize for leakage comparison: drop whitespace + comments + string/dunder noise so we
    compare CODE STRUCTURE, not formatting."""
    s = re.sub(r"#.*", "", s)
    s = re.sub(r'"""(.*?)"""', " ", s, flags=re.S)
    s = re.sub(r"'''(.*?)'''", " ", s, flags=re.S)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def _line_set(s: str) -> set:
    out = set()
    for ln in s.splitlines():
        c = re.sub(r"#.*", "", ln).strip()
        if len(c) >= 12 and not c.startswith(('"', "'", "import ", "from ")):
            out.add(re.sub(r"\s+", " ", c).lower())
    return out


def leakage_check(task: CompressTask) -> tuple:
    """Does the Σ schema leak the deliverable D? Two objective checks against EACH impl file:

      (a) substring containment: any impl file's normalized body is a substring of the normalized
          schema (the schema literally carries the implementation) -> LEAK.
      (b) high line-overlap: fraction of an impl file's substantive code lines that appear
          verbatim in the schema. If > 0.30 for any file, the schema is reconstructing the dish.

    Returns (leaked: bool, max_overlap_ratio: float, substr_hit: bool). A task that leaks is
    DROPPED by the harness (NO fabrication, and no rigging the schema to contain the answer)."""
    sch_norm = _norm(task.sigma_schema)
    sch_lines = _line_set(task.sigma_schema)
    max_ratio = 0.0
    substr_hit = False
    for src in task.impl_files.values():
        body = _norm(src)
        if len(body) >= 80 and body in sch_norm:
            substr_hit = True
        impl_lines = _line_set(src)
        if impl_lines:
            overlap = len(impl_lines & sch_lines) / len(impl_lines)
            max_ratio = max(max_ratio, overlap)
    task.leak_ratio = round(max_ratio, 4)
    task.leak_substr = substr_hit
    leaked = substr_hit or max_ratio > 0.30
    return leaked, max_ratio, substr_hit
