# 09: How are multi-recipe Videos handled?

Type: grilling
Status: resolved
Blocked by: none

## Question

When one Video contains several recipes, what gets stored?

## Answer

Each recipe is a **Recipe Part** with Item Key `platform:video_id#n`. It is extracted, grounded (quotes only from its own slice), parsed, tagged, verified and uploaded independently. It gets its own Mealie recipe, its own timestamped `orgURL` where the platform supports it, and a frame image from its start. Sibling Recipe Parts are linked in a note. A component used inside a dish ("for the marinade") is a Section, not a Recipe Part. Recorded as `docs/adr/0006-every-recipe-part-is-independent.md`. Detail: `PIPELINE_SPEC.md` §6.1.
