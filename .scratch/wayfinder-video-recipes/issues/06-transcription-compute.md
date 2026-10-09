# 06: Where does transcription run?

Type: grilling
Status: resolved
Blocked by: none

## Question

Local GPU, cloud API, or both?

## Answer

Locally on the user's Windows laptop GPU (GTX 1650, 4 GB) with `faster-whisper`, default `large-v3-turbo` `int8_float16`, picked by a benchmark ladder. OpenAI only as a capped emergency fallback. Recorded as `docs/adr/0004-local-whisper-on-gtx-1650.md`. The Windows install details are still open: see "How do faster-whisper and CUDA install on Windows for a GTX 1650?".
