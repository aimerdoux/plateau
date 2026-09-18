"""plateau.bridge._toml — a tiny fallback TOML reader for Python 3.9/3.10 (no `tomllib`).

Covers exactly what `bridge.toml` and `.plateau/config.toml` use: `[section]` tables,
plain (undotted) keys, double/single-quoted strings, integers, floats, booleans,
single-line inline tables `{ k = v, ... }`, arrays of scalars `[a, b, c]`, and `#`
comments (outside quotes). It does NOT implement the rest of the TOML spec — multi-line
strings/arrays, dotted keys, array-of-tables (`[[x]]`), dates/times, or numeric bases
other than base-10 — none of which `bridge.toml` or `.plateau/config.toml` use.

`loads(text)` must return the same dict `tomllib.loads(text)` would for those two files
(config.py picks `tomllib` when available and falls back to this module otherwise).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

_BOOL = {"true": True, "false": False}
_DQ_RE = re.compile(r'^"((?:[^"\\]|\\.)*)"$')
_SQ_RE = re.compile(r"^'([^']*)'$")
_FLOAT_RE = re.compile(r"^[+-]?\d+\.\d+(?:[eE][+-]?\d+)?$|^[+-]?\d+[eE][+-]?\d+$")
_INT_RE = re.compile(r"^[+-]?\d+$")

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "b": "\b", "f": "\f"}


def _unescape(s: str) -> str:
    out: List[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append(_ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _strip_comment(line: str) -> str:
    """Drop a trailing `# ...` comment, ignoring `#` inside a quoted string."""
    in_str, q, out = False, "", []
    i = 0
    while i < len(line):
        c = line[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if c == q:
                in_str = False
            i += 1
            continue
        if c in "\"'":
            in_str, q = True, c
            out.append(c)
            i += 1
            continue
        if c == "#":
            break
        out.append(c)
        i += 1
    return "".join(out)


def _split_top(s: str) -> List[str]:
    """Split on top-level commas: respects quotes and nested [...] / {...}."""
    parts: List[str] = []
    depth, cur, in_str, q = 0, [], False, ""
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            cur.append(c)
            if c == "\\" and i + 1 < len(s):
                cur.append(s[i + 1])
                i += 2
                continue
            if c == q:
                in_str = False
            i += 1
            continue
        if c in "\"'":
            in_str, q = True, c
            cur.append(c)
            i += 1
            continue
        if c in "[{":
            depth += 1
            cur.append(c)
            i += 1
            continue
        if c in "]}":
            depth -= 1
            cur.append(c)
            i += 1
            continue
        if c == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return [p.strip() for p in parts if p.strip()]


def _parse_scalar(v: str) -> Any:
    v = v.strip()
    if v in _BOOL:
        return _BOOL[v]
    m = _DQ_RE.match(v)
    if m:
        return _unescape(m.group(1))
    m = _SQ_RE.match(v)
    if m:
        return m.group(1)
    if v.startswith("[") and v.endswith("]"):
        return [_parse_scalar(p) for p in _split_top(v[1:-1])]
    if v.startswith("{") and v.endswith("}"):
        return _parse_inline_table(v)
    if _INT_RE.match(v):
        return int(v)
    if _FLOAT_RE.match(v):
        return float(v)
    return v  # bare word: not produced by bridge.toml / config.toml, kept as-is


def _parse_inline_table(v: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for part in _split_top(v.strip()[1:-1]):
        key, sep, val = part.partition("=")
        if not sep:
            continue
        out[key.strip().strip("\"'")] = _parse_scalar(val)
    return out


def loads(text: str) -> Dict[str, Any]:
    """Parse a TOML document into a plain dict (see module docstring for the subset)."""
    root: Dict[str, Any] = {}
    cur: Dict[str, Any] = root
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line).strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]") and not line.startswith("[["):
            name = line[1:-1].strip()
            cur = root.setdefault(name, {})
            continue
        key, sep, val = line.partition("=")
        if not sep:
            continue
        cur[key.strip().strip("\"'")] = _parse_scalar(val)
    return root
