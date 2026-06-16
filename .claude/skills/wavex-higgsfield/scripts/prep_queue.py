#!/usr/bin/env python3
"""
WaveX Higgsfield queue prep — turns a spec into an automated image-gen queue.

Reads the image-gen prompts from a wavex-spec-extractor spec.json (or a plain
prompts .txt, one per line), sets up the run dir, and writes queue.jsonl that the
agent-browser runbook (SKILL.md) consumes to drive Higgsfield's UI and drop the
generated stills into inbox/ — which wavex-produce then turns into video.

Usage:
  python3 prep_queue.py --spec runs/<id>/spec.json --root wavex_runs/<persona>
  python3 prep_queue.py --prompts prompts.txt        --root wavex_runs/<persona>
"""
import argparse
import json
from pathlib import Path


def prompts_from_spec(spec_path):
    s = json.loads(Path(spec_path).read_text())
    brief = (s.get("creative_spec_TODO") or {}).get("recreation_brief") or {}
    prompts = brief.get("image_gen_prompts") or []
    # also fold in per-shot motion notes so wavex-produce can reuse them
    shots = (s.get("creative_spec_TODO") or {}).get("shot_list") or []
    motions = [sh.get("motion") for sh in shots if sh.get("motion")]
    return prompts, motions


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--spec")
    g.add_argument("--prompts")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root)
    (root / "inbox").mkdir(parents=True, exist_ok=True)

    motions = []
    if args.spec:
        prompts, motions = prompts_from_spec(args.spec)
    else:
        prompts = [l.strip() for l in Path(args.prompts).read_text().splitlines()
                   if l.strip()]

    q = root / "queue.jsonl"
    with q.open("w") as f:
        for i, p in enumerate(prompts):
            shot = f"shot{i+1:02d}"
            rec = {
                "id": shot,
                "prompt": p,
                "out_image": f"inbox/{shot}.png",
                "motion_prompt": motions[i] if i < len(motions) else None,
                "status": "pending",
            }
            f.write(json.dumps(rec) + "\n")
            # write the motion sidecar now so wavex-produce picks it up later
            if rec["motion_prompt"]:
                (root / "inbox" / f"{shot}.txt").write_text(rec["motion_prompt"])

    print(f"queued {len(prompts)} prompt(s) -> {q}")
    print("\nNEXT (agent drives agent-browser per SKILL.md runbook):")
    print(f"  1. ensure a cloud browser + Higgsfield auth (see SKILL.md)")
    print(f"  2. for each pending row in {q}: generate in Higgsfield -> save to its out_image")
    print(f"  3. then produce video:")
    print(f"     python3 .claude/skills/wavex-produce/scripts/img2vid.py --root {root} --once")


if __name__ == "__main__":
    main()
