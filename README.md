# mealie_pipeline

Turns saved cooking videos (YouTube playlists, Instagram saved "All posts", Facebook saved items) into verified, parsed, tagged recipes in a self-hosted Mealie. The code is built by agents from tickets. This page explains how to drive them.

## What's in here

| Path | What it is |
|---|---|
| `CLAUDE.md` | Instructions every agent session reads first |
| `.scratch/wayfinder-video-recipes/map.md` | The **wayfinder map**: decisions made so far, open decision tickets, fog, out of scope |
| `.scratch/wayfinder-video-recipes/issues/` | Decision tickets (research / task / grilling) |
| `.scratch/video-recipe-pipeline/spec.md` | The **spec** the build follows |
| `.scratch/video-recipe-pipeline/issues/` | 28 **implementation tickets** (tracer-bullet slices with `Blocked by:` edges) |
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

**Follow `.scratch/video-recipe-pipeline/ORDER.md`.** Phase A gets your CSV/Excel list of recipe names into Mealie first: 01 → 02 → 03 → 26 → 06 → 27 → 08 → 22 → 28. Then Phase B improves those recipes, and Phase C builds the social-media pipeline. The graph below shows the blocking edges; ORDER.md decides the order among the tickets the graph allows.


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
22 (skip recipes already in Mealie): after 03 (builds the URL Normalizer if 04 hasn't). Needed before 18, 19, 21, 28
25 (protein tags on every recipe): after 01. Ticket 10 also waits for it. `--apply` waits for W20
26 (CSV/Excel of recipe names → Recipe Requests): after 03
27 (find each name's recipe page on the web): after 26, 06 (W21 resolved: ddgs + Claude WebSearch fallback)
28 (import the found recipes into Mealie): after 27, 02, 08, 22
19 (you + agent): after 07, 13, 14, 22, W13, W14
W20 (you + agent): after W13, and after 04, 15, 16 are done and every list is synced. Decide the final tag set (existing, new, difficulty) before any upload
21: after 10, 11, 12, 15, 16, 17, 18, 20 and W19 (confirm run defaults with you), W20 (tag taxonomy review)
23 (Auto Sync Cycle, `mp auto`): after 21
24 (schedule it in Windows Task Scheduler): after 23. Switch it on only after W19 questions 7–10
```

Tickets that can run in parallel once 03 is done: 04, 06 and 08, plus 07 and 13 once their research tickets (W17, W18) are resolved. Parallel sessions claim a ticket by committing `Status: in-progress` first. If two sessions edit the same module, run them one after the other instead.

### When an agent finishes a ticket

It sets `Status: done`, adds a `## Comments` section with what it built and the **manual check on the laptop** for you, and commits. Do the manual check when you're at the laptop, and note the result in the ticket.

## Running batches (`mp`)

```
uv run mp add --file urls.txt        # blank lines and # comments are ignored; duplicates and unsupported URLs are reported
uv run mp run --limit 20             # at most 20 items per stage; run again to continue
uv run mp status                     # per-stage counts, totals, the 10 latest errors
uv run mp retry <item_key|video_key> [--stage tag]   # run a failed item again (from the failed stage)
uv run mp reset <stage> [--failed-only]              # run a stage (and the later ones) again for everything
uv run mp run --mode update          # after a reset: PATCH recipes already in Mealie instead of skipping them
uv run mp report                     # writes reports/report.csv
```

Ctrl+C finishes the item in progress, then stops; the next `mp run` continues. A failed item is never retried by itself.

`reports/report.csv` (UTF-8 with BOM, opens in Excel) has one row per Recipe Part, plus one row for a Video that has no Recipe Part yet (for example its metadata failed):

| Column | Meaning |
|---|---|
| `item_key`, `video_url`, `platform` | identity of the Recipe Part and where it came from |
| `metadata_status` … `upload_status` | one column per stage (`metadata`, `extract`, `parse`, `tag`, `verify`, `upload`): `pending`, `running`, `done`, `failed`, `skipped`, `review`; empty = not reached |
| `score`, `outcome`, `failed_checks`, `extraction_attempts` | the Gate: Quality Score 0-100, `upload` / `upload_review` / `review`, the IDs of failed checks (H1-H5, S1-S7), and 2 when the recipe was extracted a second time after failing |
| `failure_reason` | `<stage>: <last error>` of the first failed or held-back stage |
| `mealie_slug`, `mealie_url` | where the recipe is in Mealie |
| `created_foods` | Foods first created for this Video |
| `tags` | tag names, `;`-separated |
| `warnings` | for example `image_missing` |

## The Gate (`verify` stage)

Every recipe is scored before upload: `>= 80` uploads, `60-79` uploads with the `To Review` tag (created once if missing), below 60 or a failed hard check is extracted once more (strongest model, the findings in the prompt) and otherwise held back in `review/<item_key>.md` (Sources next to the extracted recipe and every failed check) and not uploaded. Ingredients whose quoted evidence is not in the source are dropped. Thresholds and weights are in `config/settings.yaml` under `verify:`. The LLM judge (one extra Claude call) runs only when the score before it is below 90.
