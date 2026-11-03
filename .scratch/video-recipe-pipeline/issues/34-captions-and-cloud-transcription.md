# 34: YouTube captions as a Source (no audio transcription)

**What to build:** Use existing subtitles as a Source for videos whose description holds no recipe (about 700 of the user's 1,438 YouTube videos). Per ADR 0007 there is **no Whisper, local or cloud, and no audio download**. Order of attempts per video, stopping at the first that gives text:

1. **YouTube captions** (`yt-dlp --write-subs --write-auto-subs --skip-download`), cleaned to plain text. Free, no GPU.
2. **Facebook/Instagram captions** when `yt-dlp --list-subs` finds any (not verified; test first).

The cleaned text becomes a Source (`[SRC:sub]`) for the extract stage, with the same evidence rules as the description. A video with no subtitles falls through to ticket 39 (link-only stub); it is not an error.

**Blocked by:** 03

**Status:** ready-for-agent

**Read first:** `src/mealie_pipeline/pipeline.py` (extract sources), `src/mealie_pipeline/adapters/video_source.py` (`subtitles` already exists from ticket 05), `reports/youtube_status.csv` (`needs_transcription`).

- [ ] Seam tests with fake `yt-dlp` output: captions become a `sub` Source; no captions means the video continues to ticket 39's path, not `failed`.
- [ ] A video with captions reaches `extract` with the text, and its evidence quotes check out against it.
- [ ] Clean-up of caption text (timing tags, duplicated rolling lines).
- [ ] `needs_transcription` videos in `reports/youtube_status.csv` can be re-queued with one command (rename the category to `needs_subtitles`).

**Manual check on the laptop (user):** pick 5 YouTube videos whose description has no recipe; those with captions become recipes in Mealie. Run `yt-dlp --list-subs` on one Facebook and one Instagram video and report what it prints.
