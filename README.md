# mealie_pipeline

Turns saved cooking videos (YouTube playlists, Instagram saved "All posts", Facebook saved items) into verified, parsed, tagged recipes in a self-hosted Mealie. The code is built by agents from tickets. This page explains how to drive them.

## What's in here

| Path | What it is |
|---|---|
| `CLAUDE.md` | Instructions every agent session reads first |
| `.scratch/wayfinder-video-recipes/map.md` | The **wayfinder map**: decisions made so far, open decision tickets, fog, out of scope |
| `.scratch/wayfinder-video-recipes/issues/` | Decision tickets (research / task / grilling) |
| `.scratch/video-recipe-pipeline/spec.md` | The **spec** the build follows |
| `.scratch/video-recipe-pipeline/issues/` | 21 **implementation tickets** (tracer-bullet slices with `Blocked by:` edges) |
| `PIPELINE_SPEC.md` | Design reference: research, Mealie API details, rationale |
| `GLOSSARY.md`, `docs/adr/` | Domain language and recorded decisions |
| `scripts/check_mealie.py` | Standalone Mealie API check (no install needed) |
| `.claude/skills/` | Vendored [mattpocock/skills](https://github.com/mattpocock/skills) (`/wayfinder`, `/to-spec`, `/to-tickets`, `/implement`, `/tdd`, …) |

## How to drive the agents

### Right now (in parallel)

1. **You (HITL):** wayfinder ticket *Run the Mealie API check on the laptop*. Make a token, run `py scripts\check_mealie.py --write-test`, paste the report into the ticket.
2. **You (HITL):** wayfinder ticket *Which Saved List is the pilot…*. Paste your pilot list link and a few example Videos.
3. **Research agents (AFK), one session each:**
   ```
   claude --model sonnet
   > /wayfinder .scratch/wayfinder-video-recipes/map.md  — work ticket 15
   ```
   Repeat for tickets 15, 16, 17, 18. Each writes its findings into the ticket's `## Answer` and marks it `resolved`.
4. **Build agent (AFK):** start implementation ticket 01:
   ```
   claude --model sonnet
   > /implement .scratch/video-recipe-pipeline/issues/01-doctor-and-mealie-gateway.md
   ```

### After that

Always start the lowest-numbered ticket whose blockers are finished (`done` for implementation tickets, `resolved` for wayfinder tickets), **one ticket per fresh session**. The dependency graph:

```
01 ─ 02 ─┬─ 03 ─┬─ 04 ─┬─ 05 ──────────────┬─ 18 (also 09)
         │      │      └─ 14 ─┬─ 15 (W15)  │
         │      │             ├─ 16 (W16)  └─ 20 (also 19, you)
         │      │             └─ 17 (also 06)
         │      ├─ 06 ─────────────── 12 (also 07, 08)
         │      ├─ 07 (W17) ── 11 (also 09)
         │      └─ 13 (W18)
         └─ 08 ─ 09 ─ 10
22 (skip recipes already in Mealie): after 03, 04. Needed before 18, 19, 21
19 (you + agent): after 07, 13, 14, 22, W13, W14
21: after 10, 11, 12, 15, 16, 17, 18, 20 and W19 (confirm run defaults with you)
```

Tickets that can run in parallel once 03 is done: 04, 06 and 08, plus 07 and 13 once their research tickets (W17, W18) are resolved. Parallel sessions claim a ticket by committing `Status: in-progress` first. If two sessions edit the same module, run them one after the other instead.

### When an agent finishes a ticket

It sets `Status: done`, adds a `## Comments` section with what it built and the **manual check on the laptop** for you, and commits. Do the manual check when you're at the laptop, and note the result in the ticket.
