---
description: Gate facts this session produced into Plateau's bounded signal. Only facts whose Measurement (e.g. a file hash) re-verifies against the repo right now are admitted; the rest are dropped. Persists the bounded signal.
---

For each fact this session established, write an entry to `.plateau/pending_facts.json` as a
JSON list of `{claim, source, value}` — `source` is a repo-relative path and `value` is its
expected `sha256:` hash (the gate re-hashes `source` and admits the fact only if it matches).
Then gate + persist:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hook.py" post
```

Report which facts were **admitted** to the bounded signal and which were **dropped as
ungrounded** (no re-verifying Measurement). Do not claim a fact was carried unless it was admitted.
