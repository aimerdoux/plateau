"""Query-aware scoring (rung 5/6). Lexical BM25-lite over identifier-split tokens. stdlib only.
embed_score() is the single seam where a local embedding model would plug in (rung 6+)."""
import math, re, sqlite3
TOK = re.compile(r"[A-Za-z][a-z]+|[A-Z]+(?![a-z])|\d+")
def toks(s):
    return {t.lower() for t in TOK.findall(re.sub(r"[_./\\-]", " ", s or "")) if len(t) > 1}
def embed_score(query, key, detail):   # rung 6+: return cosine(embed(query), embed(key+detail)); 0 = disabled
    return 0.0
def score_nodes(c, query, tau=40.0, W=None):
    W = W or {"symbol": 1.4, "error": 1.3, "test": 1.2, "file": 1.0, "command": 0.6, "search": 0.3, "tool": 0.2}
    last = c.execute("SELECT COALESCE(MAX(id),0) FROM receipts").fetchone()[0]
    rows = c.execute("SELECT key,kind,first_rid,last_rid,degree,last_outcome,last_detail FROM nodes").fetchall()
    q = toks(query); N = max(len(rows), 1)
    df = {}
    docs = []
    for r in rows:
        d = toks(r[0]) | toks(r[6]); docs.append(d)
        for t in d: df[t] = df.get(t, 0) + 1
    out = []
    for r, d in zip(rows, docs):
        key, kind, fr, lr, deg, oc, det = r
        recency = math.exp(-(last - lr) / tau)
        struct = W.get(kind, 0.5) * (0.6 * recency + 0.4 * math.log1p(deg))
        lex = sum(math.log(1 + N / df[t]) for t in (q & d)) if q else 0.0
        lexn = lex / (1 + lex)                      # squash to [0,1)
        emb = embed_score(query, key, det)
        s = struct + (2.0 * lexn if q else 0) + 2.0 * emb   # a lexical hit outranks any structural score
        out.append((s, key, kind, lr, deg, oc, det, bool(q & d)))
    out.sort(reverse=True)
    return out
def render(scored, budget_chars, head):
    lines, used = [], len(head) + 14
    for s, key, kind, lr, deg, oc, det, hit in scored:
        line = f"[r{lr}] {kind} {key} → {oc}" + (f" ({det[:60]})" if det else "") + f" ×{deg}" + (" ★" if hit else "") + "\n"
        if used + len(line) > budget_chars: break
        lines.append(line); used += len(line)
    return lines
