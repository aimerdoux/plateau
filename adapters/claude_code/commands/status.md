---
description: Show Plateau's current carried self-state (goals/stance/lessons/pointers/gated facts) and any facts dropped as stale after re-grounding against the repo.
---

Run the Plateau adapter in `pre` mode against the current repo to see the bounded carried
signal and what re-grounding dropped as stale:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hook.py" pre
```

Summarize the carried self-state for me, and explicitly call out any facts dropped as **stale**
(reality moved, so they were not trusted).
