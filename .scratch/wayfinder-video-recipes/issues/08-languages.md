# 08: How are English, German and Urdu/Hindi recipes written?

Type: grilling
Status: resolved
Blocked by: none

## Question

Which parts of a recipe stay in the source language, and in what script?

## Answer

**Ingredients are always English** (Food, Unit, note), so Mealie keeps one food list and the shopping list merges. Recipe text follows the Recipe Language: English stays English, German stays German, Urdu/Hindi becomes **Roman Urdu/Hindi** (Latin script, creator-caption style). Language is detected per Recipe Part. Recorded as `docs/adr/0003-ingredients-always-english.md`. Detail: `PIPELINE_SPEC.md` §2c.
