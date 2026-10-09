# 13: Run unattended on Claude Pro: pause on limits, time windows, OpenAI cap

**What to build:** Make long runs safe on a Claude Pro subscription.

- **Detecting limits:** `ClaudeCliBackend` recognizes usage-limit failures (shapes recorded in wayfinder 18) and raises `UsageLimited(reset_at)`.
- **Pausing:** the Stage Runner pauses all AI stages until the reset time (or polls every 15 min when no reset time is known), keeps non-AI stages (collect, scrape, transcribe) running, then resumes.
- **Time window:** `mp run --window 23:00-07:00` only sends AI calls inside the window.
- **Usage-saving mode** (default on):
  - the `fast` tier for classification, and for parsing website-structured recipes
  - the judge skipped when the score is ≥ 90
  - one concurrent `claude -p`
- **Usage log:** every call (task, tier, model, duration, cost/usage if reported) goes to the State Store and a usage summary in `mp status`.
- **OpenAI fallback:** `OpenAIBackend` behind the same port, only with `--allow-openai`, for a task that failed twice on Claude. It records spend and refuses calls once `OPENAI_MAX_USD` (default 2) is reached.

**Blocked by:** 03; wayfinder ticket `18-claude-cli-on-windows-and-limits.md` (read its Answer for the exact limit signals, Windows executable and argument-length handling)

**Status:** ready-for-agent

**Read first:** `spec.md` modules 3 (`LLMBackend`) and 16; `docs/adr/0002`.

- [ ] Contract tests with the stub `claude` executable cover: a usage-limit result with a reset time, one without, a transient overload (retried with backoff, not paused), and success.
- [ ] Pipeline-seam test with an injected clock: the limit hits at item 3 of 10, and the run sleeps until the reset (simulated), then finishes. Non-AI stages progress during the pause.
- [ ] `--window` is tested across midnight with the injected clock.
- [ ] OpenAI: not constructed without the flag (test). With the flag, a fake HTTP server simulates spend, and calls stop at the cap with a clear message. The spend is shown in `mp status`.
- [ ] Long JSON Schemas and prompts never hit the Windows command-line limit, following wayfinder 18's guidance (for example schema via file or stdin). There is a test that a large schema still uses an argument list under 8 000 characters, or whatever limit wayfinder 18 records.
