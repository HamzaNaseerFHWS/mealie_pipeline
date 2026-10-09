# 07: Transcribe locally on the GTX 1650 when no better Source exists

**What to build:** A `transcribe` stage that decides whether a Video needs a transcript, then gets the best one:
- **Skip** when a structured website recipe exists, or the description/pinned comment already holds an ingredient list.
- **Otherwise** use creator subtitles, else download 16 kHz mono audio and run `faster-whisper` on the GPU.
- **Whisper settings:** a vocabulary prompt (title + description + units), ffmpeg clean-up filters, VAD, and `condition_on_previous_text=False`.
- **Quality flags:** silent or music-only reels with no usable caption go to the Review Queue as `needs_ocr`.
- **Output:** the transcript (with timestamps) becomes the `asr` Source.
- **Benchmark:** `mp bench-whisper` runs the model ladder on sample files and writes a comparison table, then records the chosen model in settings.
- **Classifier escalation:** ticket 05's escalation can now use the first 60 s of transcript.

**Blocked by:** 03; wayfinder ticket `17-whisper-on-windows-gtx1650.md` (install, DLLs, compute types, VRAM; read its Answer and follow it)

**Status:** ready-for-agent

**Read first:** `spec.md` modules 3 (`Transcriber`, `VideoSource.download_audio`) and 7; `PIPELINE_SPEC.md` §2b "Local transcription" and §5; `docs/adr/0004`.

- [ ] The Transcription Policy is pure and table-tested: website structured → skip; description with ≥ 3 qty+unit lines or an ingredients heading (en/de/ur/hi words) → skip; creator subs → use subs; auto-subs only as a fallback when Whisper fails; otherwise Whisper.
- [ ] Subtitle files (VTT/SRV) are parsed into timestamped segments with duplicate rolling lines removed. Tested with fixtures.
- [ ] The `faster-whisper` adapter:
  - loads the model once per run and runs one GPU job at a time
  - follows the Windows CUDA DLL setup from wayfinder 17
  - falls back down the ladder on out-of-memory
  - records the model and compute type on the transcript
  - is thin: verified manually, not in CI
- [ ] Quality signals (avg logprob, no-speech ratio, words per minute) are stored. A pure rule decides `needs_ocr` (thresholds in settings) and is table-tested.
- [ ] `mp bench-whisper --samples <dir>` runs each ladder step on each sample and prints a table (speed × real time, peak VRAM if available, and the transcript beside a reference `.txt` when given, with a word error rate). It then writes the chosen model and compute type to settings. Tested with a fake transcriber.
- [ ] Pipeline-seam test: a Video with a caption-less description and a fake transcript fixture reaches `FakeMealie`, and its Evidence quotes come from the `asr` Source.
- [ ] Downloaded audio is deleted after transcription unless `keep_audio: true`.

**Manual check on the laptop (user):** follow wayfinder 17's install steps, run `uv run mp doctor` (the GPU line should be green), then `uv run mp bench-whisper --samples <folder with 3 short clips: English, German, Urdu/Hindi>`. Paste the table into Comments.
