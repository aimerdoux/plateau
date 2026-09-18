"""Self-verify every HARD gate BEFORE any paid claude -p call (gate soundness pre-flight).

For each task we supply a KNOWN-GOOD reference solution (must PASS the gate) and at least one
KNOWN-BAD solution (a plausible-but-wrong attempt that must FAIL the gate). If a gate passes a
bad solution or fails the good one, the gate is unsound and the experiment must NOT proceed.

These reference solutions are used ONLY to validate the gates. They are NEVER shown to either
arm and are NOT the model's output — they exist solely so the objective V is proven decidable +
discriminating before we spend money. Run: python -m plateau.sigma._selftest_hard_gates
"""

from __future__ import annotations

import sys

from .ab_tasks_hard import hard_task_specs, verifier_for
from .evaluate import evaluate


def _cand(code: str) -> dict:
    return {"text": code, "code": code}


# ---- GOOD reference solutions (must PASS) ----
GOOD = {}
BAD = {}

# h1 roman
GOOD["h1_roman"] = r'''
_VALS=[(1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),(50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")]
def to_roman(n):
    if not isinstance(n,int) or isinstance(n,bool) or n<1 or n>3999:
        raise ValueError("out of range")
    out=[]
    for v,s in _VALS:
        while n>=v:
            out.append(s); n-=v
    return "".join(out)
def from_roman(s):
    if not isinstance(s,str) or not s:
        raise ValueError("empty")
    n=to_roman_check=0
    i=0; total=0
    M={"I":1,"V":5,"X":10,"L":50,"C":100,"D":500,"M":1000}
    for ch in s:
        if ch not in M: raise ValueError("bad char")
    # parse using subtractive rules
    i=0; total=0
    vals=[M[c] for c in s]
    for j in range(len(vals)):
        if j+1<len(vals) and vals[j]<vals[j+1]:
            total-=vals[j]
        else:
            total+=vals[j]
    # canonical-form check: re-encode must equal input (rejects IIII, VV, IC, MMMM...)
    if total<1 or total>3999 or to_roman(total)!=s:
        raise ValueError("non-canonical")
    return total
'''
# bad: clamps instead of raising, and no canonical check
BAD["h1_roman"] = r'''
_VALS=[(1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),(50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")]
def to_roman(n):
    n=max(1,min(3999,n))   # clamps instead of raising -> WRONG
    out=[]
    for v,s in _VALS:
        while n>=v:
            out.append(s); n-=v
    return "".join(out)
def from_roman(s):
    M={"I":1,"V":5,"X":10,"L":50,"C":100,"D":500,"M":1000}
    total=0; prev=0
    for ch in reversed(s):
        v=M.get(ch,0)
        if v<prev: total-=v
        else: total+=v; prev=v
    return total   # accepts IIII etc -> WRONG
'''

# h2 calc
GOOD["h2_calc"] = r'''
import re
def calc(expr):
    toks=re.findall(r"\d+\.?\d*|[()+\-*/^]", expr)
    if "".join(expr.split()) != "".join(toks):
        raise ValueError("bad chars")
    if not toks: raise ValueError("empty")
    pos=0
    def peek():
        return toks[pos] if pos<len(toks) else None
    def eat():
        nonlocal pos; t=toks[pos]; pos+=1; return t
    def atom():
        t=peek()
        if t=="-":
            eat(); return -atom()
        if t=="(":
            eat(); v=expr_p();
            if peek()!=")": raise ValueError("unbalanced")
            eat(); return v
        if t is None or t in "+*/^)": raise ValueError("expected atom")
        eat(); return float(t)
    def power():
        b=atom()
        if peek()=="^":
            eat(); e=power(); return b**e
        return b
    def term():
        v=power()
        while peek() in ("*","/"):
            op=eat(); r=power()
            v=v*r if op=="*" else v/r
        return v
    def expr_p():
        v=term()
        while peek() in ("+","-"):
            op=eat(); r=term()
            v=v+r if op=="+" else v-r
        return v
    v=expr_p()
    if pos!=len(toks): raise ValueError("trailing")
    return v
'''
BAD["h2_calc"] = r'''
def calc(expr):
    return eval(expr.replace("^","**"))   # wrong: ^ right-assoc ok via **, but no unary/malformed-raise discipline & '2 3' won't raise, '2**3' won't raise
'''

# h3 intervals
GOOD["h3_intervals"] = r'''
def merge_intervals(intervals):
    if not intervals: return []
    s=sorted([list(x) for x in intervals], key=lambda x:(x[0],x[1]))
    out=[s[0][:]]
    for a,b in s[1:]:
        if a<=out[-1][1]:
            out[-1][1]=max(out[-1][1],b)
        else:
            out.append([a,b])
    return out
def complement(intervals, lo, hi):
    m=merge_intervals(intervals)
    out=[]; cur=lo
    for a,b in m:
        if b<lo or a>hi: continue
        a=max(a,lo); b=min(b,hi)
        if a>cur: out.append([cur,a])
        cur=max(cur,b)
    if cur<hi: out.append([cur,hi])
    return out
'''
BAD["h3_intervals"] = r'''
def merge_intervals(intervals):
    if not intervals: return []
    s=sorted(intervals)
    out=[list(s[0])]
    for a,b in s[1:]:
        if a<out[-1][1]:        # strict < -> fails TOUCHING [1,4],[4,5]
            out[-1][1]=max(out[-1][1],b)
        else:
            out.append([a,b])
    return out
def complement(intervals, lo, hi):
    return []   # wrong
'''

# h4 lru
GOOD["h4_lru"] = r'''
from collections import OrderedDict
class LRUCache:
    def __init__(self, capacity):
        self.cap=capacity; self.d=OrderedDict()
    def get(self,key):
        if key not in self.d: return -1
        self.d.move_to_end(key); return self.d[key]
    def put(self,key,value):
        if key in self.d: self.d.move_to_end(key)
        self.d[key]=value
        if len(self.d)>self.cap: self.d.popitem(last=False)
'''
BAD["h4_lru"] = r'''
class LRUCache:
    def __init__(self, capacity):
        self.cap=capacity; self.d={}; self.order=[]
    def get(self,key):
        return self.d.get(key,-1)   # does NOT refresh recency -> WRONG
    def put(self,key,value):
        self.d[key]=value; self.order.append(key)
        if len(self.d)>self.cap:
            old=self.order.pop(0); self.d.pop(old,None)
'''

# h5 semver
GOOD["h5_semver"] = r'''
import re
def _parse(v):
    m=re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?", v)
    if not m: raise ValueError("bad semver: "+repr(v))
    major,minor,patch=int(m.group(1)),int(m.group(2)),int(m.group(3))
    pre=m.group(4)
    pre_ids=pre.split(".") if pre else []
    for pid in pre_ids:
        if pid=="" : raise ValueError("empty prerelease id")
    return (major,minor,patch,pre_ids)
def _cmp_pre(a,b):
    if not a and not b: return 0
    if not a: return 1   # no prerelease > has prerelease
    if not b: return -1
    for x,y in zip(a,b):
        xn,yn=x.isdigit(),y.isdigit()
        if xn and yn:
            c=(int(x)>int(y))-(int(x)<int(y))
        elif xn and not yn:
            c=-1
        elif yn and not xn:
            c=1
        else:
            c=(x>y)-(x<y)
        if c!=0: return c
    return (len(a)>len(b))-(len(a)<len(b))
def compare(a,b):
    pa=_parse(a); pb=_parse(b)
    for i in range(3):
        if pa[i]!=pb[i]: return -1 if pa[i]<pb[i] else 1
    return _cmp_pre(pa[3],pb[3])
'''
BAD["h5_semver"] = r'''
def compare(a,b):
    ta=tuple(int(x) for x in a.split("+")[0].split("-")[0].split("."))
    tb=tuple(int(x) for x in b.split("+")[0].split("-")[0].split("."))
    if ta<tb: return -1
    if ta>tb: return 1
    return 0   # ignores prerelease precedence entirely -> WRONG; also int() crashes won't raise cleanly for "1.0"
'''

# h6 base62
GOOD["h6_base62"] = r'''
AL="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
IDX={c:i for i,c in enumerate(AL)}
def encode62(n):
    if not isinstance(n,int) or isinstance(n,bool) or n<0: raise ValueError("neg")
    if n==0: return "0"
    out=[]
    while n>0:
        n,r=divmod(n,62); out.append(AL[r])
    return "".join(reversed(out))
def decode62(s):
    if not isinstance(s,str) or not s: raise ValueError("empty")
    n=0
    for ch in s:
        if ch not in IDX: raise ValueError("bad char")
        n=n*62+IDX[ch]
    return n
'''
BAD["h6_base62"] = r'''
AL="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
IDX={c:i for i,c in enumerate(AL)}
def encode62(n):
    if n==0: return ""    # WRONG: should be "0"
    out=[]
    while n>0:
        n,r=divmod(n,62); out.append(AL[r])
    return "".join(reversed(out))
def decode62(s):
    n=0
    for ch in s:
        n=n*62+IDX.get(ch,0)   # silently maps bad char -> WRONG (no raise)
    return n
'''

# h7 jsonpath
GOOD["h7_jsonpath"] = r'''
import re
_MISS=object()
def jget(obj, path, default=None):
    tokens=[]
    for part in path.split("."):
        m=re.match(r"([^\[\]]*)((?:\[-?\d+\])*)$", part)
        if not m: return default
        key=m.group(1)
        if key!="" : tokens.append(("k",key))
        for idx in re.findall(r"\[(-?\d+)\]", m.group(2)):
            tokens.append(("i",int(idx)))
    cur=obj
    for typ,val in tokens:
        if typ=="k":
            if isinstance(cur,dict) and val in cur:
                cur=cur[val]
            else:
                return default
        else:
            if isinstance(cur,list) and -len(cur)<=val<len(cur):
                cur=cur[val]
            else:
                return default
    return cur
'''
BAD["h7_jsonpath"] = r'''
import re
def jget(obj, path, default=None):
    # naive: dotted only; treats "x[2]" as a literal dict key -> fails list indexing entirely
    cur=obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur=cur[part]
        else:
            return default
    return cur   # WRONG: no bracket/list-index support, jget(data,"x[2]") returns default
'''

# h8 csv
GOOD["h8_csv"] = r'''
def parse_csv(text):
    if text=="" : return []
    rows=[]; field=[]; row=[]; i=0; n=len(text); in_q=False
    while i<n:
        c=text[i]
        if in_q:
            if c=='"':
                if i+1<n and text[i+1]=='"':
                    field.append('"'); i+=2; continue
                in_q=False; i+=1; continue
            field.append(c); i+=1; continue
        if c=='"':
            in_q=True; i+=1; continue
        if c==",":
            row.append("".join(field)); field=[]; i+=1; continue
        if c=="\n":
            row.append("".join(field)); rows.append(row); field=[]; row=[]; i+=1; continue
        field.append(c); i+=1
    # flush last field/row unless the text ended exactly on a newline (already flushed)
    if field or row or (text and text[-1] not in "\n"):
        row.append("".join(field)); rows.append(row)
    return rows
'''
BAD["h8_csv"] = r'''
def parse_csv(text):
    if text=="" : return []
    return [line.split(",") for line in text.split("\n") if line!=""]   # ignores quotes -> WRONG
'''

# h9 brackets
GOOD["h9_brackets"] = r'''
def is_balanced(s):
    pairs={")":"(","]":"[","}":"{"}
    opens=set("([{")
    st=[]; i=0; n=len(s); in_str=False
    while i<n:
        c=s[i]
        if in_str:
            if c=="\\":
                i+=2; continue
            if c=='"':
                in_str=False
            i+=1; continue
        if c=='"':
            in_str=True; i+=1; continue
        if c in opens:
            st.append(c)
        elif c in pairs:
            if not st or st[-1]!=pairs[c]:
                return False
            st.pop()
        i+=1
    return not st and not in_str
'''
BAD["h9_brackets"] = r'''
def is_balanced(s):
    pairs={")":"(","]":"[","}":"{"}; opens=set("([{"); st=[]
    for c in s:                       # ignores string literals -> WRONG on ("[")
        if c in opens: st.append(c)
        elif c in pairs:
            if not st or st[-1]!=pairs[c]: return False
            st.pop()
    return not st
'''

# h10 verdict json
GOOD["h10_verdict_json"] = r'''
{"gates":[{"id":"g1","passed":true,"score":1.0},{"id":"g2","passed":false,"score":0.5},{"id":"g3","passed":true,"score":1.0}],"pass_count":2,"feasibility":0.833,"verdict":"FAIL"}
'''
BAD["h10_verdict_json"] = r'''
{"gates":[{"id":"g1","passed":true,"score":1.0},{"id":"g2","passed":true,"score":0.5},{"id":"g3","passed":true,"score":1.0}],"pass_count":3,"feasibility":0.833,"verdict":"PASS"}
'''  # passed!=(score==1) for g2, verdict wrong

# h11 toposort
GOOD["h11_toposort"] = r'''
def toposort(nodes, edges):
    from collections import defaultdict, deque
    adj=defaultdict(list); indeg={n:0 for n in nodes}
    for a,b in edges:
        adj[a].append(b); indeg[b]=indeg.get(b,0)+1
        indeg.setdefault(a,0)
    q=deque([n for n in nodes if indeg[n]==0])
    out=[]
    while q:
        n=q.popleft(); out.append(n)
        for m in adj[n]:
            indeg[m]-=1
            if indeg[m]==0: q.append(m)
    if len(out)!=len(nodes):
        raise ValueError("cycle")
    return out
'''
BAD["h11_toposort"] = r'''
def toposort(nodes, edges):
    return list(nodes)   # ignores edges & never raises on cycle -> WRONG
'''

# h12 money
GOOD["h12_money"] = r'''
from decimal import Decimal, ROUND_HALF_EVEN
def _q(d): return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
def add(a,b):
    return str(_q(Decimal(a)+Decimal(b)))
def round_money(value):
    return str(_q(Decimal(value)))
def split(total, n):
    cents=int(_q(Decimal(total))*100)
    base=cents//n; rem=cents-base*n
    parts=[]
    for i in range(n):
        c=base+(1 if i<rem else 0)
        parts.append(str((Decimal(c)/Decimal(100)).quantize(Decimal("0.01"))))
    return parts
'''
BAD["h12_money"] = r'''
def add(a,b):
    return str(round(float(a)+float(b),2))    # "0.30" maybe ok but "11.0" not "11.00" -> WRONG normalization
def round_money(value):
    return str(round(float(value),2))
def split(total,n):
    p=round(float(total)/n,2)
    return [str(p)]*n    # may not sum exactly & not banker's -> WRONG
'''


def main():
    specs = {s["task_id"]: s for s in hard_task_specs()}
    all_ok = True
    print("=== HARD GATE SOUNDNESS PRE-FLIGHT (no paid calls) ===")
    for tid, spec in specs.items():
        v = verifier_for(spec)
        good = GOOD.get(tid)
        bad = BAD.get(tid)
        if good is None or bad is None:
            print(f"  {tid}: MISSING reference solution(s) — cannot validate gate"); all_ok = False; continue
        rg = evaluate(_cand(good), v)
        rb = evaluate(_cand(bad), v)
        good_pass = rg.all_pass
        bad_pass = rb.all_pass
        sound = good_pass and (not bad_pass)
        status = "OK" if sound else "UNSOUND"
        print(f"  {tid:18s} depth={spec['depth']}  good_pass={good_pass}  bad_pass={bad_pass}  -> {status}")
        if not sound:
            all_ok = False
    print("=== RESULT:", "ALL GATES SOUND" if all_ok else "SOME GATES UNSOUND — FIX BEFORE PAID RUN", "===")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
