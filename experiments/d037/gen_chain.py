#!/usr/bin/env python3
"""D-037 chain generator. Deterministic in --seed. Writes <out>/d037_target/ (6 modules, pytest suite,
per-task FIXTURE_k.md with a buried nonce) and <out>/tasks.json (prompts + check specs). stdlib only."""
import argparse, hashlib, json, os, random, textwrap
HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = ["constant", "function", "module"]          # fact kind established by task k = KINDS[(k-1) % 3]

def establish(kind, mod):
    return {
        "constant": f"add a module-level integer constant whose name ends with `_LIMIT` (choose the rest of the name yourself; it must be a new name)",
        "function": f"add a function whose name ends with `_handler` and returns the integer 7 (choose the rest of the name yourself; it must be a new name)",
        "module":   f"create a new module `d037_target/<name>_util.py` (choose `<name>` yourself, lowercase, new) containing a function `ping()` that returns the string 'pong'",
    }[kind]

def use(kind, dep_mod, dep_k):
    return {
        "constant": f"returns the `_LIMIT` constant you defined in `d037_target/{dep_mod}.py` in task {dep_k} (import it by the name you chose)",
        "function": f"calls the `_handler` function you added to `d037_target/{dep_mod}.py` in task {dep_k} and returns its result (import it by the name you chose)",
        "module":   f"imports `ping` from the `_util` module you created in task {dep_k} and returns `ping()`",
    }[kind]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, required=True); ap.add_argument("--fixture-words", type=int, required=True)
    a = ap.parse_args(); rng = random.Random(a.seed)
    vocab = open(os.path.join(HERE, "vocab.txt")).read().split()
    T = os.path.join(a.out, "d037_target"); os.makedirs(T, exist_ok=True)
    open(os.path.join(T, "__init__.py"), "w").write("")
    for i in range(6):
        open(os.path.join(T, f"mod{i}.py"), "w").write(
            f'"""Module {i} of the D-037 target."""\n\n\ndef base{i}(x):\n    return x + {i}\n\n\ndef twice{i}(x):\n    return 2 * base{i}(x)\n')
    open(os.path.join(T, "test_target.py"), "w").write(
        "from d037_target import " + ", ".join(f"mod{i}" for i in range(6)) + "\n\n\n" +
        "".join(f"def test_mod{i}():\n    assert mod{i}.twice{i}(1) == 2 * (1 + {i})\n\n\n" for i in range(6)))
    tasks = []
    for k in range(1, a.n + 1):
        nonce = "NONCE-" + hashlib.sha256(f"{a.seed}:{k}".encode()).hexdigest()[:8]
        words = [rng.choice(vocab) for _ in range(a.fixture_words)]
        pos = rng.randint(int(0.3 * len(words)), int(0.9 * len(words)))
        words.insert(pos, nonce)
        body = "\n".join(textwrap.wrap(" ".join(words), 80))
        open(os.path.join(T, f"FIXTURE_{k}.md"), "w").write(f"# Design notes for task {k} (read fully)\n\n{body}\n")
        kind = KINDS[(k - 1) % 3]; mod = f"mod{(k - 1) % 6}"; use_mod = f"mod{(k + 1) % 6}"
        p = (f"Read `d037_target/FIXTURE_{k}.md` fully and write the nonce it contains (a token of the form NONCE-xxxxxxxx) "
             f"to `d037_target/nonce_{k}.txt` as that file's only content.\n"
             f"Then, in `d037_target/{mod}.py`, {establish(kind, mod)}. In the same module also add three helper functions "
             f"`h{k}_alpha`, `h{k}_beta`, `h{k}_gamma`, each returning its own name as a string.\n")
        dep = None
        if k > 3:
            dk = k - 3; dkind = KINDS[(dk - 1) % 3]; dmod = f"mod{(dk - 1) % 6}"
            p += (f"Then, in `d037_target/{use_mod}.py`, add a function `link_{k}()` that {use(dkind, dmod, dk)}. "
                  f"Do this from your memory of the name you chose in task {dk}, without re-reading `d037_target/{dmod}.py`"
                  + ("" if dkind != "module" else " or listing the directory") + ".\n")
            dep = {"k": dk, "kind": dkind, "module": dmod}
        p += "Finally run `pytest -q d037_target` and make sure it passes."
        tasks.append({"k": k, "prompt": p, "nonce": nonce, "kind": kind, "module": mod, "use_module": use_mod, "dep": dep})
    json.dump({"seed": a.seed, "n": a.n, "fixture_words": a.fixture_words, "tasks": tasks},
              open(os.path.join(a.out, "tasks.json"), "w"), indent=1)
    print(f"wrote {a.n} tasks, fixture {a.fixture_words} words, seed {a.seed} -> {a.out}")

if __name__ == "__main__": main()
