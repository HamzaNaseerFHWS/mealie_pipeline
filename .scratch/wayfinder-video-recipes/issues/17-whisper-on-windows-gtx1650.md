# 17: How do faster-whisper and CUDA install on Windows for a GTX 1650?

Type: research
Status: open
Blocked by: none
Mode: AFK

## Question

What exact steps make `faster-whisper` run on the GPU on native Windows with Python 3.12 and a GTX 1650 (4 GB, compute capability 7.5)?

Find out and record:

1. The CTranslate2 version range that `faster-whisper` needs, its CUDA/cuDNN major versions, and the pip-installable NVIDIA runtime wheels (cuBLAS, cuDNN) that avoid a full CUDA Toolkit install. Also how to make their DLLs findable on Windows (`os.add_dll_directory`, PATH).
2. Whether `int8_float16` and `float16` work on GTX 16xx (Turing without tensor cores), and any known NaN/garbage-output or performance issues.
3. Realistic VRAM use of `large-v3-turbo` (int8_float16 and int8) and `large-v3` (int8) in 4 GB, and whether `large-v3` int8 fits.
4. How to run a quick self-test that proves GPU use (device count, a 10 s sample).
5. Whisper accuracy notes for **Urdu and Hindi** with `large-v3-turbo` vs `large-v3`, and whether forcing `language="ur"`/`"hi"` helps with code-mixed speech.

## Answer

_pending_
