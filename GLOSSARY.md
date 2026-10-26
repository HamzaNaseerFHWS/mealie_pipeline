# Video Recipe Pipeline

Turns the user's saved social-media cooking videos into verified recipes in their Mealie instance.

## Inputs

**Saved List**:
A user-owned list of saved videos on one platform: a YouTube playlist (including Watch Later and Liked), Instagram saved "All posts", or a Facebook saved collection. Registered once and re-synced.
_Avoid_: collection (except when quoting Instagram/Facebook UI), playlist (except for YouTube)

**Video**:
One post, reel or video on a platform, identified by its **Video Key** `platform:video_id` after URL normalization.
_Avoid_: post, reel, clip, item

**Video Key**:
The canonical identity of a Video, `platform:video_id` (for example `youtube:dQw4w9WgXcQ`, `instagram:C9xYz12AbCd`).
_Avoid_: URL (URLs vary, the key doesn't)

**Creator**:
The account that published a Video. Linked to their Recipe Website when one is known.
_Avoid_: channel, uploader, author

**Recipe Website**:
A creator's website that hosts written recipes, found through links in a Video's description, pinned comment, or the Creator's bio.
_Avoid_: blog, site

## Classification

**Video Label**:
The classifier's verdict for a Video: `recipe`, `recipe_partial`, `restaurant_or_place`, `ad_or_product`, `eating_or_review`, `not_food`, `uncertain`. Only `recipe` and `recipe_partial` continue.

**Override**:
A label the user set by hand in the classification CSV. Always wins over the classifier.

## Sources and evidence

**Source**:
One piece of raw text about a Video, tagged with its kind: `web` (Recipe Website), `desc` (description/caption), `cmt` (creator's pinned comment), `asr` (our transcript), `ocr` (on-screen text).
_Avoid_: input, document

**Evidence**:
A verbatim quote from a Source that an extracted ingredient or step cites.

**Grounding**:
The check that every Evidence quote actually appears in the Source it cites. Ungrounded ingredients are dropped.
_Avoid_: hallucination check

## Recipes

**Recipe Request**:
One row of a user's CSV/Excel sheet of recipe names: "find this recipe on the web and add it to Mealie". It becomes one Recipe Part with Item Key `web:<url hash>#1` once its page is found.
_Avoid_: wish, row, lookup

**Recipe Part**:
One recipe inside a Video. Every Video has one or more; a Video with several recipes has several independent Recipe Parts, keyed `platform:video_id#n`.
_Avoid_: sub-recipe (that is a section inside one recipe), segment

**Item Key**:
The identity of a Recipe Part, `platform:video_id#n`. It's stored in the Mealie recipe's `extras.item_key` and drives idempotency.

**Outline**:
The list of Recipe Parts detected in a Video, each with a title and optional start/end timestamps.

**Section**:
A titled group of ingredients or steps inside one recipe ("For the marinade"). It is not a separate Recipe Part.

**Extracted Recipe**:
The structured recipe the LLM produces for one Recipe Part, before ingredient parsing.

**Ingredient Line**:
One ingredient as a person would write it, in English ("2 tbsp olive oil, warmed"). Always English, whatever the recipe's language.

**Parsed Ingredient**:
An Ingredient Line split into quantity, unit, food and note, with the unit and food resolved to Mealie records.

**Recipe Language**:
The language of a recipe's name, description and steps: English, German, or Roman Urdu/Hindi. Ingredients are English regardless.

**Roman Urdu/Hindi**:
Urdu or Hindi written in Latin script, the way creators write captions ("Pyaz ko golden hone tak bhoon lein"). Never Devanagari or Nastaliq.

**Auto Sync Cycle**:
One unattended `mp auto` run. It re-syncs the Saved Lists that are due, processes only unfinished Videos up to a cap, uploads what passes the Gate, and writes a summary. It's started by hand or by the scheduled task.
_Avoid_: watcher, daemon, cron job

## Quality

**Quality Score**:
A 0–100 score from the verification checks. It decides upload, upload-for-review, retry, or review-only.

**Gate**:
The verification step that a Recipe Part must pass before it reaches Mealie.

**Review Queue**:
Recipe Parts (and Videos) that need a human look, written as Markdown files with the sources side by side.

## Mealie side

**Mealie Catalog**:
The tags, foods and units that already exist in Mealie, loaded at the start of a run. The pipeline never invents tags; foods and units may be created.
_Avoid_: database, master data

**Protein Tag**:
A Tag naming a recipe's main protein (Chicken, Beef, Fish, Paneer, Lentils, Beans, Cheese, …), from the approved list in `config/protein_tags.yaml`. Added by rule, never removed.
_Avoid_: meat tag, ingredient tag

**Food**, **Unit**, **Tag**:
Mealie's own records. Always English for Food and Unit.
