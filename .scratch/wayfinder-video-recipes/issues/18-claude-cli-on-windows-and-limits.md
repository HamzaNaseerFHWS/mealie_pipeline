# 18: How does `claude -p` behave on Windows, and what happens when Pro usage limits hit?

Type: research
Status: open
Blocked by: none
Mode: AFK

## Question

How should the `LLMBackend` call the Claude Code CLI from Python on Windows, and how does it detect and wait out subscription limits?

Find out and record (from the official Claude Code docs at code.claude.com and their CLI reference):

1. How Claude Code is installed on Windows and what executable a Python `subprocess` call should invoke (`claude.exe` vs a `.cmd` shim). Whether `shutil.which("claude")` finds it.
2. Passing large prompts via stdin (limit 10 MB) with **UTF-8** on Windows (Urdu/Devanagari text), and passing a JSON Schema argument without hitting the Windows command-line length limit. Can a schema be passed from a file, or must it be inline? What length limits apply?
3. The exact shape of `--output-format json` results: where `structured_output`, `result`, `is_error`, usage and cost fields are, and the exit codes.
4. What a **usage-limit** hit looks like in print mode (exit code, error category such as `rate_limit` in `system/api_retry`, the result text, any reset time), so the backend can pause until the window resets.
5. Whether `--model haiku` / `sonnet` / `opus` aliases are available on a **Pro** plan in Claude Code, and confirm the flags `--safe-mode`, `--tools ""`, `--no-session-persistence`, `--system-prompt-file`, `--json-schema`.
6. Current Anthropic guidance on using a personal subscription for scripted `claude -p` runs (link the page).

## Answer

_pending_
