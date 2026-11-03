# 35: Import saved Instagram and Facebook posts from the data exports

**What to build (built):** `mp import-instagram <folder> -c <collection> ... --name <name>` reads Instagram's `saved_posts.json` / `saved_collections.json`, and `mp import-facebook <collections.json> -c <collection> --name <name>` reads Facebook's `collections.json`. Each creates a Saved List (`instagram:<name>`, `facebook:<name>`), registers the Videos, and (Instagram only) fills the metadata from the export (caption as description, owner as channel) and records the `metadata` stage done. The normal stages then run with `mp run --list <list key>`. For the user's case this replaces the live "scroll the saved page" collectors of tickets 15 and 16: no login, no browser, no ban risk.

**Blocked by:** None

**Status:** done

**Read first:** `src/mealie_pipeline/instagram_export.py`, `tests/test_instagram_export.py`.

- [x] Instagram: caption text repaired (UTF-8 bytes written as latin-1 escapes), posts grouped by collection, `(none)` for posts in no collection, one Video per link.
- [x] Facebook: one Video per link, chosen collections only.
- [x] Tested through the CLI (3 tests).
- [ ] Facebook posts have no caption in the export: the `metadata` stage must read them with `yt-dlp`. Check it works logged out (open question).

## Comments

### Built (2026-11-03)

Real run for the user: 530 Instagram posts (collection "Food" plus posts in no collection; "Pak Food", "Food in berlin" and "Fancy Food Science" were left out on purpose). Classify: 337 recipe or partial, 193 skipped. Full run: 142 uploaded, 86 already in Mealie, 104 failed in extract (no recipe in the caption, need transcription, ticket 34), 9 upload failures (ticket 37), 1 held for review. Facebook "For later" was imported as `facebook:later` (29 links, 22 new); its metadata and classify result was still pending when this was written.

Git ignores `instagram_data/`, `facebook-*/`, the export file names and root-level CSVs.

### Deferred

- The user's Instagram `saved_posts.json` holds 1,004 posts across 16 collections; only the food ones were imported. Run the command again with other `-c` names to add more.
- Facebook `your_saved_items.json` has no links (only "saved X's post" lines), so it is not importable.
- Tickets 15 and 16 (live collectors) and their wayfinder tickets are no longer needed for this user; keep them only if the export route stops being enough.
