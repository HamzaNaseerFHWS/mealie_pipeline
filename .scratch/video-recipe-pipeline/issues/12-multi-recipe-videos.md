# 12: Split multi-recipe Videos into independent Mealie recipes

**What to build:** An `outline` stage before `extract`.

1. **Outline call:** one `strong` LLM call per Video returns the Outline. Signals are chapters, numbered caption blocks, several website recipe links (or several Recipe objects on one page), and spoken transitions.
2. **Validation (pure):** parts are non-overlapping, within the duration, and there is at least one part. A component used inside another dish ("for the marinade") is not a part.
3. **Segmentation (pure):** each part gets its own slice of each Source.
4. **Recipe Parts:** each part becomes its own Item Key `platform:video_id#n` and runs extract → parse → tag → verify → upload **independently**. Grounding only accepts quotes from the part's own slice, and one failing part never blocks its siblings.
5. **Upload:**
   - `orgURL` is timestamped on YouTube (`&t=<start>s`).
   - `extras` = `{part, of, video_key}`.
   - A note links the sibling recipes.
   - The image is the website image, else a frame grabbed at the part's start, else the thumbnail.
6. **Re-running** the outline replaces parts only when none of them has been uploaded. Otherwise it reports the mismatch for review.

**Blocked by:** 08, 07, 06

**Status:** done

**Read first:** `PIPELINE_SPEC.md` §6.1; `docs/adr/0006`; wayfinder ticket `09-multi-recipe-videos.md`.

- [ ] Outline validation and segmentation are pure and table-tested: chapters → parts; numbered caption blocks → parts; two Recipe objects on one page → two parts; a marinade section → one part; overlapping LLM timestamps → repaired or rejected per settings.
- [ ] State: Recipe Part stage records are independent. A test fails part 2's verification and confirms parts 1 and 3 upload, part 2 goes to review, and the Video shows "2/3 uploaded" in status.
- [ ] Grounding scope: a quote that exists only in part 1's slice fails Grounding for part 2.
- [ ] Payloads: a timestamped `orgURL` for YouTube; the plain URL plus `extras.part` elsewhere; sibling notes with each sibling's name (slugs are filled in after all parts upload, by a final PATCH of notes).
- [ ] The frame grab uses the `VideoSource` frame method (fake in tests). The frame image is uploaded for parts without a website image, using the same file → URL → `image_missing` fallback chain as ticket 02.
- [ ] Single-recipe Videos behave exactly as before. The ticket 02 test still passes unchanged.

## Comments

Built without ticket 07 (local transcription): the user is skipping Videos whose recipe is in neither the description nor a website link, so no transcript exists to split by time.

**Built**
- `outline.py` (pure): `caption_blocks` (numbered caption blocks; numbered method steps are not blocks), `detect_signals` (chapters, numbered caption blocks, two or more different recipes on the website page), `validate_outline` (drops components, rejects times outside the Video, repairs or rejects overlaps per `outline.overlap`, fills missing ends), `segment` (each part's own caption block + website recipe; the caption intro is shared).
- `outline` stage (per Video, after `scrape`): the `strong` LLM call (`prompts/outline.md`) is made **only when there are signals**, so single-recipe Videos make no extra call and behave as before. An unusable outline goes to review. Parts are created with `store.replace_parts` (refuses once any part has a slug, then the Video goes to review). The same outline again changes nothing.
- Each Recipe Part stores its slice (`recipe_parts.outline_json`, migration 9). Sources, extraction prompt, grounding, the judge and the Gate use only that slice plus the marked shared text, so a quote from part 1 fails Grounding for part 2.
- Upload: YouTube `orgURL` gets `&t=<start>s`; `extras.part/of`; a note "Also in this video: names"; once every part of a Video is in Mealie, one PATCH per part turns that note into links. Sibling parts' own slugs are not treated as "already in Mealie".
- Image: website image, else a frame at the part's start (`VideoSource.frame`, fake and yt-dlp + ffmpeg), else the thumbnail chain of ticket 02.
- `mp status` lists `<video>: n/m uploaded` for multi-recipe Videos; `report.csv` has an `outline_status` column.
- Tests: `tests/test_outline_pure.py`, `tests/test_outline_seam.py` (part 2 fails Grounding while 1 and 3 upload; sibling links; rerun keeps parts). Two older tests adjusted for the new stage: the report column list, and the multi-recipe page test now scripts a one-part outline.

**Deferred**
- Splitting by transcript timestamps and spoken transitions (needs ticket 07).
- Several *different* website pages for several parts: only recipes on the one page `scrape` fetched are matched to parts.
- Parts without times (caption blocks only) get no frame; they use the thumbnail.
- No test for the frame being used when the website image is missing beyond the part 1/3 call check, and none for a failed `outline` LLM call.

**Manual verification (laptop)**
1. Pick a YouTube video with chapters and a caption listing the recipes (for example 3 chutneys). `uv run mp add <url>`, then `uv run mp run --dry-run --limit 1`, then a real run.
2. `uv run mp status` should show `<video>: 3/3 uploaded`. In Mealie each recipe should have its own start-time frame image, an `orgURL` ending `&t=<seconds>s`, and an "Also in this video" note with links.
3. Check `ffmpeg` works (`uv run mp doctor`), since frame grabs need it. If a frame can't be grabbed the thumbnail is used.
