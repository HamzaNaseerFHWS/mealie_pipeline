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

**Status:** ready-for-agent

**Read first:** `PIPELINE_SPEC.md` §6.1; `docs/adr/0006`; wayfinder ticket `09-multi-recipe-videos.md`.

- [ ] Outline validation and segmentation are pure and table-tested: chapters → parts; numbered caption blocks → parts; two Recipe objects on one page → two parts; a marinade section → one part; overlapping LLM timestamps → repaired or rejected per settings.
- [ ] State: Recipe Part stage records are independent. A test fails part 2's verification and confirms parts 1 and 3 upload, part 2 goes to review, and the Video shows "2/3 uploaded" in status.
- [ ] Grounding scope: a quote that exists only in part 1's slice fails Grounding for part 2.
- [ ] Payloads: a timestamped `orgURL` for YouTube; the plain URL plus `extras.part` elsewhere; sibling notes with each sibling's name (slugs are filled in after all parts upload, by a final PATCH of notes).
- [ ] The frame grab uses the `VideoSource` frame method (fake in tests). The frame image is uploaded for parts without a website image, using the same file → URL → `image_missing` fallback chain as ticket 02.
- [ ] Single-recipe Videos behave exactly as before. The ticket 02 test still passes unchanged.
