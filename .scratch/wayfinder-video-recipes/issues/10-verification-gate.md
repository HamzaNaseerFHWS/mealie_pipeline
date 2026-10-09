# 10: What must a recipe pass before it reaches Mealie?

Type: grilling
Status: resolved
Blocked by: none

## Question

How strict is the pipeline, and what happens to recipes that fail?

## Answer

A Gate with hard checks (is a recipe, ≥ 2 ingredients and ≥ 1 step, Grounding, every ingredient has a Food, ≥ 1 Tag) and scored soft checks, giving a Quality Score. ≥ 80 uploads. 60–79 uploads with the `To Review` tag. Below 60 or a hard fail retries once with the findings in the prompt, then goes to the Review Queue without uploading. Thresholds are config. The defaults are confirmed in "Confirm run defaults before the full run". Detail: `PIPELINE_SPEC.md` §9.
