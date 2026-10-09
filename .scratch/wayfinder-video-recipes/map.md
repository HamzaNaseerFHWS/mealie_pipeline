# Wayfinder map: video recipes into Mealie

Labels: wayfinder:map

## Destination

Every decision needed to **build and run** the pipeline over all of the user's Saved Lists (YouTube, Instagram "All posts", Facebook saved) is settled, written into `.scratch/video-recipe-pipeline/spec.md`, and sliced into agent-ready implementation tickets that Sonnet agents can build one per session without asking the user questions.

## Notes

- Domain: personal data pipeline, Python 3.12 on **Windows**, Mealie v3.x as storage (`http://mealie.taildce5a6.ts.net:9000`, Tailscale), AI through `claude -p` on Claude Pro, local Whisper on a GTX 1650.
- Read `GLOSSARY.md` and `docs/adr/` before any ticket. Research tickets also read `PIPELINE_SPEC.md`, which holds earlier research.
- **Plan, don't do.** These tickets record decisions and facts. The only code they may touch is the standalone check script `scripts/check_mealie.py`. Product code is built from the implementation tickets in `.scratch/video-recipe-pipeline/issues/`.
- Research tickets (AFK) write their findings into the ticket's `## Answer` (with source links). That's where the implementation tickets that depend on them read them. No research branches are used in this local-markdown setup.
- HITL tickets (task/grilling) are resolved **only** with the user. An agent must never fill in the user's side.
- Charting note: most of this map was resolved in the planning conversation before charting (tickets 01–12), so `/to-spec` and `/to-tickets` ran right after charting. The open tickets below gate **specific implementation tickets** (named in each implementation ticket's `Blocked by:`), not the whole build.

## Decisions so far

- [What does the pipeline take as input?](issues/01-pipeline-input.md): the user's Saved Lists on YouTube, Instagram (All posts) and Facebook, plus plain URL files. Re-syncable.
- [Use Mealie's built-in import, or our own pipeline?](issues/02-own-pipeline-vs-mealie-import.md): our own. Mealie is storage plus Catalog only (ADR 0001).
- [What exactly does Mealie's API require to store a fully parsed, tagged recipe?](issues/03-mealie-api-contract.md): create + PATCH with existing food/unit IDs; filter by `org_url`.
- [How does the pipeline get into private Saved Lists?](issues/04-private-list-access.md): separate Playwright Chrome profile, manual login once, cookies exported for yt-dlp (ADR 0005).
- [Which Videos count as recipes?](issues/05-what-counts-as-a-recipe.md): recipe + partial + drinks continue. Restaurants, ads, eating videos skipped. User Overrides win.
- [Where does transcription run?](issues/06-transcription-compute.md): local faster-whisper on the GTX 1650, benchmark ladder (ADR 0004).
- [Which LLM backend?](issues/07-llm-backend.md): `claude -p` on Claude Pro. OpenAI emergency-only and capped (ADR 0002).
- [How are English, German and Urdu/Hindi recipes written?](issues/08-languages.md): ingredients always English. Text in English / German / Roman Urdu-Hindi (ADR 0003).
- [How are multi-recipe Videos handled?](issues/09-multi-recipe-videos.md): independent Recipe Parts `platform:video_id#n` end to end (ADR 0006).
- [What must a recipe pass before it reaches Mealie?](issues/10-verification-gate.md): hard checks plus Quality Score. ≥ 80 upload, 60–79 upload with `To Review`, else Review Queue.
- [Which Roman Urdu/Hindi spelling style?](issues/11-romanization-style.md): common creator-caption style, chosen by the planner.
- [Where does everything run?](issues/12-runtime-environment.md): Windows laptop, Mealie on another PC via Tailscale. Agents test with fakes.

## Not yet specified

- **Rule-tag mapping:** which of the user's actual Mealie tags rule-based tagging targets (vegetarian, quick, drinks, cuisine). Graduates once "Run the Mealie API check on the laptop" returns the tag list. It's folded into "Confirm run defaults before the full run" question 6, which now waits on [Which existing tags do we keep, and which new tags does the collection need?](issues/20-tag-taxonomy-review.md). That ticket runs after the Saved Lists are enumerated and before any upload, and decides the final tag set, including new cuisines, ingredient types and difficulty.
- **Per-language Whisper model:** whether Urdu/Hindi needs a different model than `large-v3-turbo`. Graduates after the benchmark runs on the laptop with an Urdu/Hindi sample (implementation ticket "Benchmark and choose the Whisper model on the laptop").
- **Classifier calibration:** the confidence threshold and rule weights that reach ≥ 95 % on the pilot. Graduates when the pilot list is known and the classifier exists (implementation ticket "Calibrate the classifier on the pilot list").

## Out of scope

- On-screen text OCR for silent reels: the pipeline routes such Videos to the Review Queue with reason `needs_ocr`. OCR itself is a later effort.
- TikTok and other platforms beyond YouTube, Instagram and Facebook.
- Mealie categories, tools, nutrition, meal plans, and attaching video files as assets.
- Running the pipeline on the Mealie PC, multi-user use, and any public hosting.
