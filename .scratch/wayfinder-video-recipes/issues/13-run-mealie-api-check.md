# 13: Run the Mealie API check on the laptop

Type: task
Status: open
Blocked by: none
Mode: HITL (only the user can reach the Mealie PC)

## Question

Does the Mealie instance accept a token-authenticated write of a fully parsed, tagged recipe, and what is in its Catalog (version, tags, foods, units)?

## Checklist for the user

1. In Mealie (`http://mealie.taildce5a6.ts.net:9000`), open your avatar → **Profile** → **API Tokens**, create a token named `mealie-pipeline`, and copy it. It's shown once.
2. On the laptop, in this repo folder, run in PowerShell:
   ```powershell
   $env:MEALIE_TOKEN = "<paste token>"
   py scripts\check_mealie.py --url http://mealie.taildce5a6.ts.net:9000 --write-test
   ```
3. All lines should say `OK`. The script creates a throwaway recipe, checks the parsed ingredient, tag, `orgURL`, `extras` and the `org_url` search, then deletes it.
4. Paste the contents of `mealie_check_report.json` (it contains no token) as the answer below.
5. Keep the token for the pipeline's `.env` (`MEALIE_TOKEN=...`).

## Answer

_pending_
