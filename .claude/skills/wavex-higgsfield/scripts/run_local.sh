#!/usr/bin/env bash
# WaveX — local one-shot on your own Mac:
#   spec.json  ->  Higgsfield images (agent-browser)  ->  video (fal.ai)
#
# Prereqs (one time):
#   npm i -g agent-browser && agent-browser install
#   agent-browser open https://higgsfield.ai/login   # log in once
#   agent-browser state save ./higgsfield-auth.json
#   python3 -m pip install --user yt-dlp faster-whisper av fal-client
#   export FAL_KEY=...                                # for the video stage
#
# Usage:
#   bash run_local.sh calibrate                       # open create page + snapshot
#   bash run_local.sh run <run-root> <spec.json>      # full pipeline
#
# After `calibrate`, set the 3 selectors below to match the snapshot, then `run`.
set -euo pipefail

# ── CALIBRATE THESE from `bash run_local.sh calibrate` ───────────────────────
HF_CREATE_URL="${HF_CREATE_URL:-https://higgsfield.ai/create/image}"
PROMPT_PLACEHOLDER="${PROMPT_PLACEHOLDER:-Describe}"   # prompt box placeholder text
GENERATE_LABEL="${GENERATE_LABEL:-Generate}"          # generate button label
# JS returning the newest generated image URL (Higgsfield-specific; calibrate):
RESULT_IMG_JS="${RESULT_IMG_JS:-(() => { const i=[...document.querySelectorAll(\"img\")].filter(x=>/cdn|media|generat/i.test(x.src)); return i.length?i[i.length-1].src:\"\"; })()}"
GEN_TIMEOUT="${GEN_TIMEOUT:-180}"                     # seconds to wait per image
# ─────────────────────────────────────────────────────────────────────────────

STATE="${STATE:-./higgsfield-auth.json}"
AB=(agent-browser --state "$STATE")
SKILLS="$(cd "$(dirname "$0")/../../.." && pwd)"      # -> .claude/skills

calibrate() {
  "${AB[@]}" open "$HF_CREATE_URL"
  "${AB[@]}" wait 3000
  echo "================ SNAPSHOT (paste this back to Claude) ================"
  "${AB[@]}" snapshot -i
  echo "====================================================================="
  "${AB[@]}" screenshot /tmp/hf_create.png >/dev/null && \
    echo "screenshot: /tmp/hf_create.png (send if helpful)"
}

gen_one() {            # $1=prompt  $2=out_png
  local prompt="$1" out="$2" url="" waited=0
  "${AB[@]}" open "$HF_CREATE_URL"
  "${AB[@]}" wait 2500
  "${AB[@]}" find placeholder "$PROMPT_PLACEHOLDER" fill "$prompt"
  "${AB[@]}" find text "$GENERATE_LABEL" click
  # poll for the finished image url
  while [ "$waited" -lt "$GEN_TIMEOUT" ]; do
    url="$("${AB[@]}" eval "$RESULT_IMG_JS" 2>/dev/null | tr -d '"' || true)"
    [ -n "$url" ] && [[ "$url" == http* ]] && break
    sleep 5; waited=$((waited+5))
  done
  if [ -n "$url" ] && [[ "$url" == http* ]]; then
    curl -fsSL "$url" -o "$out" && echo "  saved $out"
  else
    echo "  ! no image url after ${GEN_TIMEOUT}s — re-calibrate RESULT_IMG_JS" >&2
    return 1
  fi
}

run() {
  local root="${1:?run <run-root> <spec.json>}" spec="${2:?run <run-root> <spec.json>}"
  python3 "$SKILLS/wavex-higgsfield/scripts/prep_queue.py" --spec "$spec" --root "$root"
  local tmp="$root/queue.done.jsonl"; : > "$tmp"
  while IFS= read -r line; do
    local id prompt out
    id="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["id"])' "$line")"
    prompt="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["prompt"])' "$line")"
    out="$root/$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["out_image"])' "$line")"
    echo "[$id] generating…"
    if gen_one "$prompt" "$out"; then
      echo "$line" | python3 -c 'import json,sys;d=json.loads(sys.stdin.read());d["status"]="done";print(json.dumps(d))' >> "$tmp"
    else
      echo "$line" >> "$tmp"
    fi
  done < "$root/queue.jsonl"
  mv "$tmp" "$root/queue.jsonl"
  echo "=== images done -> producing video ==="
  python3 "$SKILLS/wavex-produce/scripts/img2vid.py" --root "$root" --once
  echo "=== DONE: clips in $root/outbox/ ==="
}

case "${1:-}" in
  calibrate) calibrate ;;
  run) shift; run "$@" ;;
  *) echo "usage: bash run_local.sh {calibrate | run <run-root> <spec.json>}"; exit 1 ;;
esac
