# Local faster-whisper on a 4 GB GTX 1650

Transcription runs locally with `faster-whisper` on the user's GTX 1650 (4 GB, compute capability 7.5, no tensor cores). The default is `large-v3-turbo` with `int8_float16`. A benchmark command picks from a ladder (turbo int8_float16 → turbo int8 → medium/small) on the real card. Full `large-v3` is not the default because it doesn't reliably fit in 4 GB. Cloud transcription (OpenAI) is only a capped emergency fallback.
