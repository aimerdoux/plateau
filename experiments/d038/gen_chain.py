#!/usr/bin/env python3
"""D-038 chain generator. Deterministic in --seed. Writes under <out>/:
  tasks.json                     prompts + check specs
  gate.sh                        `node --check` on every module + `node --test` on the classify gate
  concierge-agent/FIXTURE_k.md   per-task ballast with one buried nonce (D-037 A5)
  concierge-agent/d038.test.mjs  the gate test (imports classify.mjs only)
The real target is NOT written here: run_arm.py copies it from --target into <out>/concierge-agent/ at run time, so
nothing from the private repo lands in this public tree. stdlib only."""
import argparse, hashlib, json, os, random, textwrap
HERE = os.path.dirname(os.path.abspath(__file__))
VOCAB = os.path.join(HERE, "..", "d037", "vocab.txt")            # the same 2059-word vocabulary as D-037
T = "concierge-agent"                                              # target dir inside the worktree
FILES = ["server.mjs", "agent.mjs", "classify.mjs", "qa.mjs", "qa-corpus.mjs", "train.mjs"]  # task k establishes in FILES[(k-1) % 6]
USE_FILES = [f for f in FILES if f != "classify.mjs"]            # the gate imports classify.mjs, so it never imports a sibling
KINDS = ["constant", "function", "module"]                         # fact kind established by task k = KINDS[(k-1) % 3]

def establish(kind, f):
    return {
        "constant": f"in `{T}/{f}`, add a new module-level exported integer constant (`export const <NAME> = <integer>;`, "
                    f"UPPER_SNAKE_CASE; choose the name yourself; it must be new in that file)",
        "function": f"in `{T}/{f}`, add a new exported function (`export function <name>() {{ return 7; }}`; choose the name "
                    f"yourself; it must be new in that file)",
        "module":   f"create a new module `{T}/<name>-util.mjs` (choose `<name>` yourself, lowercase, new) that exports a "
                    f"function `ping()` returning the string 'pong'",
    }[kind]

def use(kind, dep_file, dep_k):
    return {
        "constant": f"returns the exported integer constant you added to `{T}/{dep_file}` in task {dep_k} (import it by the name you chose)",
        "function": f"calls the exported function you added to `{T}/{dep_file}` in task {dep_k} and returns its result (import it by the name you chose)",
        "module":   f"imports `ping` from the `-util.mjs` module you created in task {dep_k} and returns `ping()`",
    }[kind]

GATE = """#!/usr/bin/env bash
# D-038 gate: every module must still parse; classify.mjs must still import and classify.
set -eu; cd "$(dirname "$0")/concierge-agent"
for f in *.mjs; do node --check "$f"; done
node --test d038.test.mjs
echo GATE OK
"""
TEST = """import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classify } from './classify.mjs';
test('classify still exports a working classifier', () => {
  assert.equal(typeof classify, 'function');
  assert.equal(classify({ product_type: 'rental', product_name: 'Sunset yacht' }, { category: 'boat' }), 'boat');
  assert.equal(classify({ product_type: 'rental', product_name: 'Lamborghini' }, { category: 'exotic car' }), 'car');
  assert.equal(classify({ product_type: 'experience', product_name: 'Spa day' }, null), 'manual');
});
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, required=True); ap.add_argument("--fixture-words", type=int, required=True)
    a = ap.parse_args(); rng = random.Random(a.seed)
    vocab = open(VOCAB).read().split()
    td = os.path.join(a.out, T); os.makedirs(td, exist_ok=True)
    g = os.path.join(a.out, "gate.sh"); open(g, "w").write(GATE); os.chmod(g, 0o755)
    open(os.path.join(td, "d038.test.mjs"), "w").write(TEST)
    tasks = []
    for k in range(1, a.n + 1):
        nonce = "NONCE-" + hashlib.sha256(f"d038:{a.seed}:{k}".encode()).hexdigest()[:8]
        words = [rng.choice(vocab) for _ in range(a.fixture_words)]
        pos = rng.randint(int(0.3 * len(words)), int(0.9 * len(words)))
        words.insert(pos, nonce)
        body = "\n".join(textwrap.wrap(" ".join(words), 80))
        open(os.path.join(td, f"FIXTURE_{k}.md"), "w").write(f"# Design notes for task {k} (read fully)\n\n{body}\n")
        kind = KINDS[(k - 1) % 3]; f = FILES[(k - 1) % 6]
        dep = None; dfile = None
        if k > 3:
            dk = k - 3; dfile = FILES[(dk - 1) % 6]; dep = {"k": dk, "kind": KINDS[(dk - 1) % 3], "file": dfile}
        # use file: rotate over USE_FILES from offset k+1, skipping this task's own file and the dependency's file
        use_file = next(u for u in (USE_FILES[(k + 1 + i) % len(USE_FILES)] for i in range(len(USE_FILES)))
                        if u != f and u != dfile)
        p = (f"Read `{T}/FIXTURE_{k}.md` fully and write the nonce it contains (a token of the form NONCE-xxxxxxxx) "
             f"to `{T}/nonce_{k}.txt` as that file's only content.\n"
             f"Then {establish(kind, f)}. Also, in `{T}/{f}`, add three exported helper functions "
             f"`h{k}_alpha`, `h{k}_beta`, `h{k}_gamma`, each returning its own name as a string.\n")
        if dep:
            p += (f"Then, in `{T}/{use_file}`, add an exported function `link_{k}()` that {use(dep['kind'], dfile, dep['k'])}. "
                  f"Do this from your memory of the name you chose in task {dep['k']}, without re-reading `{T}/{dfile}`"
                  + ("" if dep["kind"] != "module" else " or listing the directory") + ".\n")
        p += "Finally run `bash gate.sh` and make sure it passes."
        tasks.append({"k": k, "prompt": p, "nonce": nonce, "kind": kind, "file": f, "use_file": use_file, "dep": dep})
    json.dump({"seed": a.seed, "n": a.n, "fixture_words": a.fixture_words, "target": T, "files": FILES, "tasks": tasks},
              open(os.path.join(a.out, "tasks.json"), "w"), indent=1)
    print(f"wrote {a.n} tasks, fixture {a.fixture_words} words, seed {a.seed} -> {a.out}")

if __name__ == "__main__": main()
