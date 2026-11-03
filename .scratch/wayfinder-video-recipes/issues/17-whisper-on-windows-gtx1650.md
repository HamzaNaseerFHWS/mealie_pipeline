# 17: How do faster-whisper and CUDA install on Windows for a GTX 1650?

Type: research
Status: resolved
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

Researched 2026-10-30 from primary sources only (faster-whisper repo and PyPI, CTranslate2 docs/releases/PyPI, NVIDIA wheels on PyPI, OpenAI Whisper discussions, Hugging Face cards). Anything not confirmed there is marked **unverified**. Nothing was installed or run, so every GPU claim still needs the laptop check at the end.

### 1. Versions, runtime wheels and DLLs on Windows

- **Current releases:** `faster-whisper` 1.2.1 (2025-10-31, Python ≥ 3.9) ([PyPI](https://pypi.org/project/faster-whisper/)). `ctranslate2` 4.8.4 (2026-10-25) has a `cp312 win_amd64` wheel (20.4 MB) ([PyPI](https://pypi.org/project/ctranslate2/)).
- **Required runtime:** the latest CTranslate2 supports only **CUDA 12 and cuDNN 9**. Older combos are pins: CUDA 11 + cuDNN 8 → `ctranslate2==3.24.0`; CUDA 12 + cuDNN 8 → `ctranslate2==4.4.0` ([faster-whisper README](https://github.com/SYSTRAN/faster-whisper#gpu)). We use the current combination, so no ctranslate2 pin is needed beyond a sane range (below).
- **cuDNN is now optional for Whisper's conv layer:** CTranslate2 4.6.3 (2026-01-06) added CUDA 12.8 support and a pure-CUDA `Conv1d` that "makes cuDNN an optional dependency" ([release notes](https://github.com/OpenNMT/CTranslate2/releases/tag/v4.6.3)). Whether cuDNN can then be dropped entirely for faster-whisper is **unverified**. Plan to install it anyway, because it is the documented setup and a cuDNN mismatch is the most common Windows failure ([issue #1080](https://github.com/SYSTRAN/faster-whisper/issues/1080)).
- **pip wheels exist for Windows:** `nvidia-cublas-cu12` 12.9.2.10 has a `win_amd64` wheel (553 MB) ([PyPI](https://pypi.org/project/nvidia-cublas-cu12/)). `nvidia-cudnn-cu12` 9.27.0.42 has a `win_amd64` wheel (743 MB) ([PyPI](https://pypi.org/project/nvidia-cudnn-cu12/)). The README's pip route is documented for **Linux only** (`LD_LIBRARY_PATH`); its Windows route is Purfview's DLL archive added to `PATH` ([README](https://github.com/SYSTRAN/faster-whisper#gpu)). An old maintainer comment says pip cuDNN doesn't work on Windows, but that predates the Windows wheels, and 2025 comments in the same thread report pip + `os.add_dll_directory` working ([issue #153](https://github.com/SYSTRAN/faster-whisper/issues/153)). Treat pip-on-Windows as **plausible but not officially documented**.
- **Known working pin set (from issue #1080, cuDNN 9.5 era, Windows venv):** `nvidia-cudnn-cu12==9.5.0.50`, `nvidia-cuda-nvrtc-cu12==12.4.127`, `nvidia-cuda-runtime-cu12==12.4.127`, `nvidia-cublas-cu12==12.4.5.8` ([issue #1080](https://github.com/SYSTRAN/faster-whisper/issues/1080)). Whether the newest wheels (cuBLAS 12.9, cuDNN 9.27) also work with ctranslate2 4.8.x is **unverified**; start with the newest, fall back to that set if loading fails.
- **Making DLLs findable:** the 2025 reports add the wheel `bin` folders (`site-packages\nvidia\cublas\bin`, `...\cudnn\bin`, `...\cuda_runtime\bin`) to `PATH` (and/or `os.add_dll_directory`) **before** importing `ctranslate2`/`faster_whisper` ([#1080](https://github.com/SYSTRAN/faster-whisper/issues/1080), [#153](https://github.com/SYSTRAN/faster-whisper/issues/153)). Do both: `add_dll_directory` is the Python 3.8+ way, but CTranslate2 loads some cuDNN sub-DLLs itself, so also prepend to `PATH`. Copy the whole cuDNN DLL set, not only `cudnn_ops64_9.dll`.
- **Driver:** the CTranslate2 prebuilt binaries need an NVIDIA GPU with compute capability ≥ 3.5 and a driver new enough for the CUDA version ([hardware support](https://opennmt.net/CTranslate2/hardware_support.html)). The GTX 1650 is 7.5. The minimum driver for CUDA 12.x was not looked up here; **needs checking** (`nvidia-smi`).
- **Suggested `pyproject.toml` pins (for ticket 07, adjust after the laptop check):**
  ```
  faster-whisper>=1.2.1,<2
  ctranslate2>=4.6.3,<5      # cuDNN-optional Conv1d, CUDA 12.8
  nvidia-cublas-cu12>=12.4,<13 ; sys_platform == "win32"
  nvidia-cudnn-cu12>=9.5,<10   ; sys_platform == "win32"
  ```
  (Ship the NVIDIA wheels as an optional `gpu` extra: ~1.3 GB, and CI/agent sessions must not need them.)
- **Windows DLL helper (put in the adapter, call before importing faster-whisper):**
  ```python
  import os, sys, site
  from pathlib import Path
  def add_nvidia_dll_dirs() -> list[str]:
      if sys.platform != "win32": return []
      added = []
      for sp in site.getsitepackages():
          for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
              d = Path(sp) / "nvidia" / sub / "bin"
              if d.is_dir():
                  os.add_dll_directory(str(d))
                  os.environ["PATH"] = str(d) + os.pathsep + os.environ["PATH"]
                  added.append(str(d))
      return added
  ```
- **Model names:** `large-v3` → `Systran/faster-whisper-large-v3`; `turbo`/`large-v3-turbo` → `mobiuslabsgmbh/faster-whisper-large-v3-turbo` ([utils.py](https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/utils.py)). `deepdml/faster-whisper-large-v3-turbo-ct2` is an equivalent community FP16 conversion, MIT, ~100 languages ([model card](https://huggingface.co/deepdml/faster-whisper-large-v3-turbo-ct2)). Use the built-in alias.

### 2. `float16` and `int8_float16` on a GTX 1650

- CTranslate2 documents `float16` and `int8_float16` as **natively supported from compute capability 7.0 up** (table row "≥ 7.0, < 8.0": float16 → float16, int8_float16 → int8_float16). Below 7.0 they silently fall back to float32/int8_float32 ([quantization docs](https://opennmt.net/CTranslate2/quantization.html)). So both are *documented* to work on CC 7.5. `int8_float32` is the documented fallback for plain int8 on 7.x, so `int8` there means int8 weights with float32 compute (higher VRAM than `int8_float16`).
- **Turing without tensor cores (GTX 16xx):** no primary source says CTranslate2 treats it differently from other 7.5 cards. Expect float16 to work but with less speed-up than on RTX cards. **Unverified.**
- **NaN/garbage:** the only primary hit is a PyTorch issue of fp16 producing NaN on GTX 1660 / 1660 Ti with CUDA 11.1 ([pytorch#58123](https://github.com/pytorch/pytorch/issues/58123)). That is PyTorch, not CTranslate2, and I found **no** faster-whisper issue tying NaN or garbage output to GTX 16xx. It is still a plausible risk, so the adapter should sanity-check (see ticket 07 list).
- **Always call `ctranslate2.get_supported_compute_types("cuda")`** at start-up and only choose from what it returns. The docs also say `compute_type="auto"` picks the fastest supported type, and `CT2_VERBOSE=1` shows detected capabilities ([quantization docs](https://opennmt.net/CTranslate2/quantization.html)).

### 3. VRAM in 4 GB

No primary source gives numbers for large-v3-turbo or large-v3 on a 4 GB card. The only primary benchmark is for **large-v2** (same 1550 M size as large-v3) on an RTX 3070 Ti, CUDA 12.4, beam 5, one clip ([README benchmarks](https://github.com/SYSTRAN/faster-whisper#benchmark)):

| Setup | VRAM |
|---|---|
| large-v2 fp16, beam 5 | 4525 MB (won't fit) |
| large-v2 int8, beam 5 | 2926 MB |
| large-v2 int8, `batch_size=8` | 4500 MB (won't fit) |

- **large-v3 int8:** large-v3 has the same architecture as large-v2 apart from 128 mel bins ([announcement](https://github.com/openai/whisper/discussions/1762)), so ~3 GB at beam 5, batch 1 is the best estimate. It **probably fits in 4 GB but with little headroom**; the benchmark number likely includes the CUDA context, and Windows plus Chrome/display use some of the 4 GB. **Unverified on this card.** Use beam 1–2 to leave room.
- **large-v3-turbo:** 809 M parameters, 4 decoder layers instead of 32 ([model card](https://huggingface.co/openai/whisper-large-v3-turbo)). Weights at int8 are roughly half those of large-v3, so it should sit well under large-v3's figure (rough guess 1.5–2 GB, **unverified**; secondary sites say ~1.5 GB, not primary). `int8_float16` and `int8` should be close. It is the first rung to try.
- **Never use batched mode** (`BatchedInferencePipeline`/`batch_size`) on this card: the README shows int8 batch 8 already needs 4.5 GB.
- **Suggested ladder:** `large-v3-turbo` int8_float16 → `large-v3-turbo` int8 → `large-v3` int8 (only if the benchmark shows it fits and helps Urdu) → `medium`/`small` int8 → CPU int8. Catch `RuntimeError` mentioning out of memory (exact message **unverified**) and step down.

### 4. Self-test script (proves GPU use)

Put this in `mp doctor` (or `scripts/gpu_selftest.py`). It uses only documented calls: `ctranslate2.get_cuda_device_count()` and `get_supported_compute_types()` are listed in the [CTranslate2 Python API](https://opennmt.net/CTranslate2/python/ctranslate2.html) (exact signatures **unverified**; the page only lists the names).

```python
import sys, time, subprocess, shutil
add_nvidia_dll_dirs()                      # helper from section 1, BEFORE these imports
import ctranslate2
from faster_whisper import WhisperModel

n = ctranslate2.get_cuda_device_count()
print("cuda devices:", n)
assert n >= 1, "CTranslate2 sees no GPU (driver/DLL problem)"
types = ctranslate2.get_supported_compute_types("cuda")
print("compute types:", sorted(types))

# 10 s sample from any file (ffmpeg is on PATH in this project)
subprocess.run(["ffmpeg", "-y", "-i", sys.argv[1], "-t", "10", "-ar", "16000", "-ac", "1", "sample10.wav"], check=True)
ct = "int8_float16" if "int8_float16" in types else "int8"
t0 = time.time()
model = WhisperModel("turbo", device="cuda", compute_type=ct)   # device="cuda" fails loudly if no GPU
print("load s:", round(time.time() - t0, 1))
t0 = time.time()
segs, info = model.transcribe("sample10.wav", beam_size=1)
text = " ".join(s.text for s in segs)
print("lang:", info.language, round(info.language_probability, 2), "| s:", round(time.time() - t0, 1))
print(text)
print(subprocess.run([shutil.which("nvidia-smi"), "--query-gpu=name,memory.used,memory.total", "--format=csv"],
                      capture_output=True, text=True).stdout)   # run while the model is loaded
assert text.strip(), "empty transcript"
```

A pass means: device count ≥ 1, no `cudnn_*64_9.dll` / `cublas64_12.dll` error, non-empty sensible text, a transcription time clearly under the clip length, and `nvidia-smi` showing memory used by the process. `device="cuda"` raises instead of silently using CPU, which is what proves GPU use. Cross-check with Task Manager's GPU "CUDA" graph.

### 5. Urdu / Hindi accuracy

- **Primary figures are thin.** Whisper maintainers report large-v3-turbo Urdu at **26.5 % WER (Common Voice 15)** and **21.9 % (FLEURS)**, and say turbo "performs similarly to large-v2" overall with big losses only on e.g. Thai and Cantonese ([turbo announcement](https://github.com/openai/whisper/discussions/2363)). No Hindi figure for turbo is given there. For large-v3 the announcement chart claims 10–20 % lower error than large-v2 on languages under 60 % error, and a commenter measured ~37 % Hindi WER vs a quoted 16.9 %, unresolved ([large-v3 announcement](https://github.com/openai/whisper/discussions/1762)). So: **large-v3 vs turbo for Urdu/Hindi is not settled by primary sources**; the benchmark in ticket 07 on the user's own clips is the right way to decide.
- **Treat Hindi/Urdu as a weak-ish language for any Whisper size.** The Whisper model card warns of lower accuracy on low-resource languages and of hallucination/repetition ([turbo card](https://huggingface.co/openai/whisper-large-v3-turbo)). The large-v3 thread has many hallucination reports on silent or music-only audio ([thread](https://github.com/openai/whisper/discussions/1762)), which matches the pipeline's VAD and `needs_ocr` design.
- **Turbo is not trained for translation**: do not use `task="translate"`; keep `task="transcribe"` ([turbo announcement](https://github.com/openai/whisper/discussions/2363)).
- **Forcing `language`:** in faster-whisper, if `language` is unset it is detected from the first 30 s; `language_detection_threshold` (default 0.5) and `language_detection_segments` (default 1) control detection ([transcribe.py](https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/transcribe.py)). Setting it skips detection, so it removes wrong-language and Hindi-vs-Urdu mix-ups. **Whether forcing helps code-mixed speech accuracy has no primary evidence.** Reasoning only (unverified): a forced code decides the output script and the decoder's language prior, so English words inside Urdu speech tend to be transcribed in that script or dropped, and a mislabeled clip can't be corrected mid-way. Use forcing when the language is known from metadata, keep detection on otherwise, and compare both in `bench-whisper` on a code-mixed clip.
- **Script/romanization:** base Whisper has no setting for Roman Urdu or Hinglish. A third-party Urdu fine-tune advertises a decode-time script token, and a Hinglish fine-tune reports far lower WER than base large-v3 ([Oriserve model card](https://huggingface.co/Oriserve/Whisper-Hindi2Hinglish-Prime/blob/main/README.md), [emads urdu-v2](https://huggingface.co/emads/whisper-large-v3-urdu-v2)). These are self-reported and not in scope; mentioned only as a later option if base models disappoint. Using `initial_prompt` text in the target script, plus the title/description vocabulary already planned, is the cheap lever ([transcribe.py](https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/transcribe.py): applies to the first window only).

### What ticket 07 should do

1. Add the NVIDIA wheels as a Windows-only optional `gpu` extra (pins above) and call `add_nvidia_dll_dirs()` (both `os.add_dll_directory` and `PATH`) before the first `ctranslate2`/`faster_whisper` import.
2. At start-up call `ctranslate2.get_cuda_device_count()` and `get_supported_compute_types("cuda")`; never request a type that isn't listed. Fail loudly (no silent CPU) unless the user allows CPU.
3. Default ladder: `turbo` int8_float16 → `turbo` int8 → `large-v3` int8 (benchmark-gated) → `small`/`medium` int8 → CPU int8. Step down on out-of-memory. Use `beam_size` 1–2, no batched mode, one GPU job at a time.
4. Run `float16` only as an opt-in benchmark rung. Add a sanity check on the output (empty text, a single repeated token, or avg logprob far below the other rungs → treat as bad compute type and step down).
5. Use `language=` from the Video's metadata when known (en/de/ur/hi), else auto-detect; record the detected language and probability on the transcript. In `bench-whisper`, include one code-mixed clip and run each rung with forced vs auto language so the table settles the question.
6. Keep `condition_on_previous_text=False`, `vad_filter=True`, `task="transcribe"`; pass the vocabulary prompt via `initial_prompt` (first window only).
7. `mp doctor`: embed the self-test above; print device count, compute types, DLL dirs added, and a green/red GPU line with the actual error text on failure.
8. Log peak VRAM in `bench-whisper` via `nvidia-smi --query-gpu=memory.used` sampling, since no in-process API was verified.

### Needs checking on the laptop

- `nvidia-smi` driver version is new enough for CUDA 12.x, and the GPU reports CC 7.5.
- The newest NVIDIA wheels (cuBLAS 12.9, cuDNN 9.27) load with ctranslate2 4.8.x on native Python 3.12; if not, try the #1080 pin set, then Purfview's DLL archive.
- Whether it runs without cuDNN installed at all (4.6.3 Conv1d note), to save 743 MB.
- `get_supported_compute_types("cuda")` output on the 1650 (expect `float16` and `int8_float16` per the docs).
- `float16` vs `int8_float16` transcripts on one clip: identical-ish text, no NaN/garbage, and the real speed difference (GTX 16xx has no tensor cores).
- Actual peak VRAM and speed (× real time) for turbo int8_float16, turbo int8 and large-v3 int8 with Chrome open; whether large-v3 int8 survives a 5-minute clip without out-of-memory.
- Out-of-memory exception type/message from CTranslate2 so the ladder catches the right error.
- Urdu, Hindi and a code-mixed clip: turbo vs large-v3, forced `ur`/`hi` vs auto, and whether output is Urdu/Devanagari script or romanized.
