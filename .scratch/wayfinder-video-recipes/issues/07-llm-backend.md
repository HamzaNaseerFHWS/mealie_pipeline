# 07: Which LLM backend?

Type: grilling
Status: resolved
Blocked by: none

## Question

API key, subscription, or local model?

## Answer

The user's **Claude Pro** subscription through `claude -p` with `--json-schema`. Haiku for classification and easy parsing; Sonnet for extraction, outlining, romanization and verification. Usage-saving mode is on by default. OpenAI is emergency-only, behind `--allow-openai` and `OPENAI_MAX_USD`. Recorded as `docs/adr/0002-claude-cli-on-subscription.md`. The Windows subprocess details and rate-limit signals are still open: see "How does `claude -p` behave on Windows and when Pro limits hit?".
