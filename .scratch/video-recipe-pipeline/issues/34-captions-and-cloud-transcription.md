# 34: Transcripts without a local GPU: YouTube captions first, a cloud service second

**What to build:** A cheaper alternative to ticket 07 for videos whose description holds no recipe (about 700 of the user's 1,438 YouTube videos, and many Instagram/Facebook posts). Order of attempts per video, stopping at the first that gives text:

1. **YouTube captions** (`yt-dlp --write-subs --write-auto-subs --skip-download`), cleaned to plain text. Free, no GPU, YouTube only.
2. **Facebook captions** when `yt-dlp --list-subs` finds any (not verified; test first).
3. **Cloud speech-to-text** on the downloaded audio (`yt-dlp -x`, `ffmpeg`): Groq Whisper (reported free tier: 28,800 audio seconds per day, 25 MB file limit; check Groq's rate-limits page before relying on it), behind a small `Transcriber` port so Deepgram or local `faster-whisper` (ticket 07) can be swapped in. A daily quota guard: stop and resume the next day instead of failing items.
4. Local `faster-whisper` (ticket 07) stays an option when a GPU is available.

The transcript becomes a Source (`[SRC:transcript]`) for the extract stage, with the same evidence rules as the description. Videos in the `needs_transcription` category of `reports/youtube_status.csv` are the first users.

Audio of the user's saved videos goes to a third party in step 3: make it an explicit setting (`transcription.cloud: false` by default) and ask the user before enabling it.

**Blocked by:** 03; the user must agree to a cloud service for step 3.

**Status:** ready-for-agent

**Read first:** `.scratch/video-recipe-pipeline/issues/07-local-transcription.md`, `src/mealie_pipeline/pipeline.py` (extract sources), `reports/youtube_status.csv` (`needs_transcription`).

- [ ] Seam tests with a fake `Transcriber` and fake `yt-dlp` output: captions win over audio; the cloud step is skipped when disabled; quota exhausted means "retry tomorrow", not "failed".
- [ ] A video with captions reaches `extract` with a transcript, and its evidence quotes check out against it.
- [ ] Clean-up of caption text (timing tags, duplicated rolling lines).
- [ ] `needs_transcription` videos can be re-queued with one command.

**Manual check on the laptop (user):** pick 5 `needs_transcription` YouTube videos; they become recipes in Mealie. Run `yt-dlp --list-subs` on one Facebook and one Instagram video and report what it prints.
