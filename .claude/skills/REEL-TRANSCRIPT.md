# Instagram Reel — Transcript & Skill Install Guide

**Source:** https://www.instagram.com/reel/DYh0vdAv2_s/
**Creator:** @cindie.zhu
**Topic:** "Build an entire creative studio inside Claude with ~7 skills"

## Transcript (auto-generated via faster-whisper)

> Did you know that you can now build an entire creative studio inside of Claude
> with just seven skills? Before you spend thousands of dollars and thousands of
> hours trying to build a creative studio...
>
> **Remotion** — Connect it with Claude and it adds animations and graphics to
> your video. It can even create full explainer videos on whatever you're working
> on. No editing needed.
>
> **Competitor ads extractor** — This skill pulls live competitor ads, which means
> all their messaging, hooks and CTAs that are working right now. Perfect for
> competitor research.
>
> **Number three, deep research** — A more agent that runs market analysis while
> you work. Incredibly helpful for market research.
>
> **Number four, voice DNA** — This one extracts your sentence rhythm and
> vocabulary so that any copy that Claude writes will sound exactly as if you
> wrote it.
>
> **Number five, ElevenLabs (11 Labs)** — Give it any document and it becomes a
> narrated audio or like a two-person podcast in like one minute.
>
> **Number six, content research writer** — The full package: it does content
> research, copywriting, and fact-checks with citations.
>
> Overall five of these are completely free; I think only ElevenLabs needs [a
> paid plan]. Comment "skill" for the full install guide for all five.

## Skills installed (mapped from the transcript)

| # | Mentioned as | Installed skill | Source |
|---|--------------|-----------------|--------|
| 1 | Remotion | `remotion-best-practices` | `remotion-dev/skills` |
| 2 | Competitor ads extractor | `competitive-ads-extractor` | `davila7/claude-code-templates` |
| 3 | Deep research | `deep-research` | `davila7/claude-code-templates` |
| 4 | Voice DNA | `voice-dna-creator` | `az9713/ai-co-writing-claude-skills` |
| 5 | ElevenLabs | `text-to-speech` | `elevenlabs/skills` |
| 6 | Content research writer | `content-research-writer` | `davila7/claude-code-templates` |

Plus `faster-whisper` (`theplasmak/faster-whisper`) — the local speech-to-text
skill used to transcribe the reel itself.

## How they were installed

```bash
npx skills add <owner/repo@skill> -a claude-code -y --copy
```

Files live in `.claude/skills/` and are picked up automatically by Claude Code.

> Note: `text-to-speech` (ElevenLabs) requires an `ELEVENLABS_API_KEY`; the other
> five run free. `remotion-best-practices` needs Node + the Remotion packages in
> the project where you render video.
