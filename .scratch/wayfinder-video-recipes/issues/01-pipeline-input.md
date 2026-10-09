# 01: What does the pipeline take as input?

Type: grilling
Status: resolved
Blocked by: none

## Question

Does the pipeline start from the user's own uploads, from single URLs, or from lists the user has saved, and on which platforms?

## Answer

From the user's **Saved Lists**: YouTube playlists (including private ones, Watch Later and Liked), Instagram saved **"All posts"**, and Facebook saved items/collections. About 300 Videos per platform, mostly by other Creators. The pipeline enumerates the Video URLs itself and can re-sync later to pick up new saves. A plain file of URLs is also accepted. Design detail: `PIPELINE_SPEC.md` §3.
