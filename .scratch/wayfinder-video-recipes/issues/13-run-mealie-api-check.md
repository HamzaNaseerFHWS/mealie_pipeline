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
3. All lines should say `OK`. The script creates a throwaway recipe, checks the parsed ingredient, tag, `orgURL`, `extras` and the `org_url` search, then deletes it. It also counts your existing recipes by source site (for example how many came from instagram.com), which tells ticket 22 how many earlier imports to protect.
4. Paste the contents of `mealie_check_report.json` (it contains no token) as the answer below.
5. Keep the token for the pipeline's `.env` (`MEALIE_TOKEN=...`).

## Answer

_pending_

## Comments

### Partial evidence, 2026-10-10 (does not resolve this ticket)

A token was created at *Profile → API Tokens* and a recipe was written by hand over Tailscale, without `scripts/check_mealie.py`. Results:

- Reachable at `http://mealie.taildce5a6.ts.net:9000`; **version v3.22.0** (ticket 03 was written from v3.28.0 source).
- Token valid (`GET /api/users/self`), create + PATCH of a recipe with `orgURL` and fully structured ingredients (quantity, unit, food, note) works and reads back correctly.
- Still unverified, so this stays open: tags, `extras`, the `org_url` search, image upload, delete, and the catalog and per-site recipe counts that `check_mealie.py --write-test` reports.
- A leftover test recipe `chatpata-bhindi-aloo` and some new foods/units are in the instance; details are in the Comments of implementation ticket 01. Delete the recipe before reading the existing-recipe counts for ticket 22.
- Gotchas found are written up in ticket 01's Comments (`abbreviation` must be `""` not null; catalog names need case-insensitive matching).
