"""plateau.sigma.compress_eval — run the OBJECTIVE V (original test suite) against a reproduced
package, in a fresh isolated subprocess. NO transcript content is ever executed as a command;
we write the candidate's files + the original test verbatim to a temp dir and run pytest/unittest
on them in a clean interpreter. The verdict is the test runner's own pass/fail.

A6 holds: the test suite (V) was authored IN THE ORIGINAL SESSION, by neither the COLD arm nor the
SIGMA arm. Both arms are scored by the SAME V. The scorer here is mechanical: write files, run the
suite, read the exit code + summary.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile


def _pytest_python() -> str:
    """Find a python interpreter that has pytest (the suites mix unittest-class + pytest-function
    styles; pytest collects both). Falls back to the harness interpreter (unittest-only)."""
    cands = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), ".venv", "bin", "python"),
        sys.executable,
    ]
    for py in cands:
        if py and os.path.exists(py):
            try:
                r = subprocess.run([py, "-c", "import pytest"], capture_output=True, timeout=20)
                if r.returncode == 0:
                    return py
            except Exception:
                continue
    return sys.executable


def _split_files(reply: str) -> dict:
    """Parse an arm's reply into {relpath: source}. Two accepted shapes:

      (a) `# FILE: path` line immediately followed by a ```python ... ``` block (the schema asks
          for this).
      (b) bare fenced ```python blocks with a leading `# path` or module hint; falls back to a
          single module named after the package if no path markers are present.

    DATA only — never executes anything it parses."""
    files = {}
    # shape (a): # FILE: <path> then a fence
    pat = re.compile(r"#\s*FILE:\s*([^\n]+?)\s*\n+```(?:python|py)?\s*\n(.*?)```", re.S | re.I)
    for m in pat.finditer(reply):
        path = m.group(1).strip().strip("`").strip()
        files[path] = m.group(2)
    if files:
        return files
    # shape (b): fenced blocks, look for a leading "# path/to.py" comment inside
    for m in re.finditer(r"```(?:python|py)?\s*\n(.*?)```", reply, re.S | re.I):
        body = m.group(1)
        head = body.splitlines()[0] if body.splitlines() else ""
        hm = re.match(r"#\s*([\w./-]+\.py)\s*$", head.strip())
        if hm:
            files[hm.group(1).strip()] = "\n".join(body.splitlines()[1:])
        else:
            files.setdefault("__single__", body)
    return files


def _layout_paths(impl_files: dict) -> list:
    return sorted(impl_files.keys())


def run_v(reply: str, *, pkg: str, test_name: str, test_src: str,
          required_layout: list, timeout: int = 120) -> dict:
    """Write the arm's reproduced package + the ORIGINAL test into a temp dir and run it.

    Returns {pass: bool, returncode, summary, n_parsed_files, wrote_layout, stdout_tail}.
    Pass iff the runner reports success (unittest OK / pytest 'N passed' with 0 failed/errors).
    """
    parsed = _split_files(reply)
    result = {"pass": False, "returncode": None, "summary": "", "n_parsed_files": len(parsed),
              "wrote_layout": [], "stdout_tail": ""}
    if not parsed:
        result["summary"] = "no files parsed from reply"
        return result

    with tempfile.TemporaryDirectory() as tmp:
        # If the arm used the # FILE: convention, honor its paths (relative to tmp).
        # Else, if a single block came back, drop it at the package's primary module path.
        layout = required_layout or list(parsed.keys())
        if "__single__" in parsed and len(parsed) == 1:
            # best-effort: write the single block to every required module is wrong; instead
            # write it as the first required module and create __init__ if package-shaped.
            primary = layout[0] if layout else f"{pkg}.py"
            parsed = {primary: parsed.pop("__single__")}

        written = []
        for rel, src in parsed.items():
            rel = rel.lstrip("/").replace("..", "")
            dest = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dest) or tmp, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(src if isinstance(src, str) else str(src))
            written.append(rel)
        result["wrote_layout"] = sorted(written)

        # ensure package __init__ exists if the test imports a package
        pkg_dir = os.path.join(tmp, pkg)
        if os.path.isdir(pkg_dir) and not os.path.exists(os.path.join(pkg_dir, "__init__.py")):
            open(os.path.join(pkg_dir, "__init__.py"), "w").close()

        # write the ORIGINAL test (the objective V) verbatim
        test_path = os.path.join(tmp, test_name)
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(test_src)

        env = dict(os.environ)
        env["PYTHONPATH"] = tmp + os.pathsep + env.get("PYTHONPATH", "")
        # The deliverables + suites are stdlib-only but mix unittest-class and pytest-function
        # styles. Run with pytest (collects both) under an interpreter that has it; the objective
        # V is decided purely by the runner's own pass/fail exit. Fall back to unittest if pytest
        # is unavailable (works for the unittest-class suites).
        py = _pytest_python()
        used = "pytest"
        cmd = [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header", test_path]
        try:
            p = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                               timeout=timeout, env=env)
            out = (p.stdout or "") + "\n" + (p.stderr or "")
            rc = p.returncode
            if "No module named pytest" in out or "No module named 'pytest'" in out:
                raise FileNotFoundError
        except subprocess.TimeoutExpired:
            result["summary"] = f"TIMEOUT after {timeout}s"
            return result
        except FileNotFoundError:
            used = "unittest"
            cmd = [sys.executable, "-m", "unittest", "-v", test_name[:-3]]
            p = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                               timeout=timeout, env=env)
            out = (p.stdout or "") + "\n" + (p.stderr or "")
            rc = p.returncode

        result["runner"] = used
        result["returncode"] = rc
        result["stdout_tail"] = out[-1800:]
        passed = False
        n_ran = 0
        if used == "pytest":
            mp = re.search(r"(\d+)\s+passed", out)
            mf = re.search(r"(\d+)\s+(failed|error)", out)
            n_ran = int(mp.group(1)) if mp else 0
            n_ran += sum(int(x) for x in re.findall(r"(\d+)\s+(?:failed|error)", out))
            passed = bool(mp) and not mf and rc == 0 and n_ran >= 1
            result["summary"] = (mp.group(0) if passed else
                                 (mf.group(0) if mf else
                                  re.search(r"(no tests ran|errors?[^\n]*|collected 0[^\n]*)", out,
                                            re.I).group(0) if re.search(r"no tests ran|error|collected 0", out, re.I)
                                  else f"rc={rc}"))
        else:
            ran = re.search(r"Ran\s+(\d+)\s+test", out)
            n_ran = int(ran.group(1)) if ran else 0
            passed = (rc == 0 and "\nOK" in ("\n" + out) and "FAILED" not in out and n_ran >= 1)
            result["summary"] = (f"unittest OK ({n_ran})" if passed else
                                 (re.search(r"FAILED \([^\n)]*\)|No module[^\n]*|ImportError[^\n]*|"
                                            r"SyntaxError[^\n]*|Ran 0[^\n]*", out) or
                                  type("x", (), {"group": lambda s, n=0: f"rc={rc}"})()).group(0))
        result["n_ran"] = n_ran
        result["pass"] = passed
    return result


def reassemble_original(impl_files: dict) -> str:
    """Build a synthetic ARM reply that reproduces D_orig verbatim (for the sanity reference run):
    emit each impl file in the `# FILE:` convention so run_v writes them faithfully."""
    parts = []
    for rel in sorted(impl_files):
        parts.append(f"# FILE: {rel}\n```python\n{impl_files[rel]}\n```")
    return "\n\n".join(parts)
