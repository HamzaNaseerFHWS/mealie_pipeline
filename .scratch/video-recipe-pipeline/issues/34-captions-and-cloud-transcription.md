# 34: YouTube captions as a Source (no audio transcription)

**What to build:** Use existing subtitles as a Source for videos whose description holds no recipe (about 700 of the user's 1,438 YouTube videos). Per ADR 0007 there is **no Whisper, local or cloud, and no audio download**. Order of attempts per video, stopping at the first that gives text:

1. **YouTube captions** (`yt-dlp --write-subs --write-auto-subs --skip-download`), cleaned to plain text. Free, no GPU.
2. **Facebook/Instagram captions** when `yt-dlp --list-subs` finds any (not verified; test first).

The cleaned text becomes a Source (`[SRC:sub]`) for the extract stage, with the same evidence rules as the description. A video with no subtitles falls through to ticket 39 (link-only stub); it is not an error.

**Blocked by:** 03

**Status:** done

**Read first:** `src/mealie_pipeline/pipeline.py` (extract sources), `src/mealie_pipeline/adapters/video_source.py` (`subtitles` already exists from ticket 05), `reports/youtube_status.csv` (`needs_transcription`).

- [x] Seam tests with fake `yt-dlp` output: captions become a `sub` Source; no captions means the video continues to ticket 39's path, not `failed`.
- [x] A video with captions reaches `extract` with the text, and its evidence quotes check out against it.
- [x] Clean-up of caption text (timing tags, duplicated rolling lines).
- [x] `needs_transcription` videos in `reports/youtube_status.csv` can be re-queued with one command (rename the category to `needs_subtitles`).

**Manual check on the laptop (user):** pick 5 YouTube videos whose description has no recipe; those with captions become recipes in Mealie. Run `yt-dlp --list-subs` on one Facebook and one Instagram video and report what it prints.

## Comments

**Built**
- **Subtitles as a Source:** scrape fetches the Video's subtitles when two things are true: no website recipe was found, and neither the description nor the pinned comment has usable text (ticket 39's rule). It uses the existing `VideoSource.subtitles`: the creator's track first, else automatic captions, in the Video's own language, then English.
  - The text is saved to `data/<platform>/<id>/subtitles.txt`, capped at 20,000 characters. An empty file means "has none", so a run doesn't ask again.
  - It becomes the `sub` Source (`[SRC:sub]`) for extraction, grounding and the outline prompt (so ticket 36 can split on it). `SourceKind` gains `sub`, and the extract prompt describes it.
  - No subtitles means the Video goes on to a link-only stub (ticket 39), not `failed`. A yt-dlp error while reading subtitles is a run warning; the Video still goes on, and the next scrape asks again.
- **Caption clean-up (`vtt_text`):** removes the WEBVTT header, cue timings, SRT cue numbers, inline `<c>` and timing tags, `[Music]` and ♪, and HTML entities (`&amp;`). It merges YouTube's rolling auto-caption lines (a cue that repeats or extends the line before).
- **`mp requeue-subtitles [--csv reports/youtube_status.csv]`:** resets `scrape` and every later stage for each Video that:
  - had an extraction fail for lack of text, or
  - is marked `needs_transcription` / `needs_subtitles` in the status sheet. The sheet's `needs_transcription` values are renamed to `needs_subtitles`.

  The video key is taken from a `video_key` / `item_key` / `url` / `video_url` column. I couldn't see `reports/youtube_status.csv` (it's on the laptop), so the command finds the column by its value rather than by a fixed column name.
- Still no Whisper and no audio download (ADR 0007).

**Facebook/Instagram:** the same `subtitles` call is used for every platform. If yt-dlp lists no subtitles, the Video becomes a stub. Not verified against real IG/FB posts (that's the manual check below).

**Manual check on the laptop (user):**
- `uv run mp requeue-subtitles`, then `uv run mp run --limit 5`. YouTube videos with captions become recipes; the ones without become link-only stubs.
- Run these and tell me what they print:

```
yt-dlp --list-subs "<a Facebook video URL>"
```

```
yt-dlp --cookies secrets/cookies.txt --list-subs "<an Instagram reel URL>"
```
