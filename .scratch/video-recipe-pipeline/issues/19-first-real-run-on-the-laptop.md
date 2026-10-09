# 19: First real run on the laptop (pilot list)

**What to build:** Nothing new in code. This is the user's guided first run on the real machine, with an agent helping in a live session. It turns the manual checks of earlier tickets into one checklist and records the results.

**Blocked by:** 07, 13, 14, 22; wayfinder tickets `13-run-mealie-api-check.md` and `14-pilot-list.md`

**Status:** ready-for-human

- [ ] Install: Python 3.12, `uv`, ffmpeg (`winget install Gyan.FFmpeg`), Claude Code logged in with Pro, `uv sync`, `uv run playwright install chrome` if needed, the CUDA wheels per wayfinder 17.
- [ ] `.env` filled in (`MEALIE_URL=http://mealie.taildce5a6.ts.net:9000`, `MEALIE_TOKEN`). `uv run mp doctor` is all green, and its output is pasted into Comments.
- [ ] `uv run mp bench-whisper` run with an English, a German and an Urdu/Hindi clip. The chosen model is recorded. If Urdu/Hindi quality is poor, decide here (with the user) between a per-language model, preferring subtitles, or the OpenAI fallback for ur/hi, and record it.
- [ ] `uv run mp login youtube` (plus instagram/facebook if the pilot list is there).
- [ ] Existing-recipe check: on a list containing reels you already imported, `--dry-run` shows them as `already_in_mealie`. Check `reports/existing_matches.csv` with the user.
- [ ] The pilot list from wayfinder 14 is added and synced, and the run uses `--limit 20 --dry-run` first. The payloads in `work/` look right.
- [ ] Real run `--limit 20`. Results reviewed in Mealie with the user. Problems become new tickets (`needs-triage`) under this folder.
- [ ] The usage summary from `mp status` is recorded (how many recipes fit one Pro window).
