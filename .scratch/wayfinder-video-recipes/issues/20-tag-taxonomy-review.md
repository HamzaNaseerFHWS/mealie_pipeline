# 20: Which existing tags do we keep, and which new tags does the collection need?

Type: grilling
Status: open
Blocked by: 13
Mode: HITL

**Runs after** the collect stage has enumerated every Saved List (implementation tickets 04, 15 and 16 done and synced), and **before** any recipe is uploaded (tickets 19, 21 and the tagging config in ticket 10). It needs the full list of Videos, because the right tags depend on what is actually in it.

## Question

Given the user's real Mealie tags and the real contents of their Saved Lists, what is the final tag set the pipeline may use, and which new tags must be created in Mealie first?

The pipeline never invents tags (wayfinder 19 q2, ticket 10): the LLM and the Rule Tags can only pick tags that already exist. So a missing tag means a recipe goes untagged or mis-tagged. This ticket closes that gap up front.

## Prep (an agent does this before the live session)

1. Pull the full tag list: `GET /api/organizers/tags?perPage=-1`. On 2026-10-10 this returned 53 tags: cuisines (Indian, Italian, Mexican, Asian, …), proteins and ingredients (Chicken, Beef, Salmon, Potato, Rice, Pasta, Mushroom, …), dishes (Cake, Salad, Sauce, Snack, Dessert, Drink, …) and a few one-offs. Re-pull it, it will have changed.
2. Flag tidy-up candidates in the existing list, without changing anything:
   - near-duplicates and typos (`Choclate` / `Chocolate`, `PIckle`, `Sandiwch`)
   - over-specific tags that look like one-off recipes (`Lemon Chicken Orzo Soup`, `Rice Paper Hacks`)
   - tags that overlap in meaning
3. Export the collected Videos (title, creator, description or caption, platform, list) to a scratch CSV. If the State Store has no export yet, a throwaway script is fine. It is not product code.
4. Survey the list for what the current tags cannot express. Count roughly how many Videos each gap affects. Look at least at:
   - **cuisine / nationality** (Pakistani, Turkish, Korean, Japanese, Thai, German, Chinese, …)
   - **main protein**: the Protein Tag list for ticket 25 (Chicken, Beef, Lamb & Mutton, Fish, Seafood, Turkey, Pork, Egg, Tofu, Paneer, Cheese, Lentils, Beans, Chickpeas, Soy chunks). Confirm the names, merge or split (Fish vs Salmon, Lamb vs Mutton, Paneer vs Cheese), and confirm that `mp tags protein --apply` may create the missing ones.
   - **ingredient and spice types** (okra, paneer; spice-heavy, curry, masala)
   - **dish type** (curry, soup, bread, stir-fry, breakfast, sweet)
   - **difficulty** (easy / medium / hard)
   - **effort** (quick, meal-prep, one-pot, air-fryer, no-cook)
   - **diet** (vegetarian, vegan, high-protein, low-carb, gluten-free)
   - **drinks and occasions** (chai, smoothie, Ramadan, party)
5. Propose, per gap: **add a new tag**, **reuse an existing tag**, or **leave out**, with the Video count behind it.

## Decide with the user (`/grilling`, one question at a time)

1. Which existing tags are kept as they are, merged, renamed or deleted? (Merge and delete are done by the user in Mealie, never by the pipeline.)
2. Which new tags are created, and in which exact spelling? Cuisine tags follow the existing style (`Indian`, not `India`).
3. Difficulty: do we want it at all? If yes, which scale, and which signal decides it (step count, active time, technique)? Is it a Rule Tag (deterministic) or an LLM choice?
4. Which dimensions are Rule Tags and which are LLM choices? This feeds the mapping in wayfinder 19 q6 and `config/tag_rules.yaml`.
5. How many tags per recipe, and is any dimension mandatory (for example always exactly one cuisine)?
6. How do the approved new tags get into Mealie? The pipeline itself only creates `To Review` (ADR 0001, wayfinder 19). Options: the user creates them in the Mealie UI, or a one-off `scripts/` helper reads the approved list and `POST`s each to `/api/organizers/tags`. Pick one.

Never answer on the user's behalf.

## Answer

_pending_

When resolved, the Answer must contain:
- the **final tag list**, grouped by dimension, marking which are existing and which are new
- the tidy-up actions the user took or will take in Mealie
- the Rule Tag mapping to hand to `config/tag_rules.yaml` (this also answers wayfinder 19 q6)
- the tag-creation method chosen in q6
- the confirmed Protein Tag list for `config/protein_tags.yaml` (ticket 25)

## Comments

- 2026-10-10: Context from a hand-run test. A recipe pushed through the API had no tags until the PATCH set `tags: [{id, name, slug}]` with ids that already exist. PATCH never creates a tag. The 53 tags and 7 categories (Appetizer, Dessert, Main Dish, Sauce, Side Dish, Snack, Soup) were readable with the same token. Categories stay out of scope for v1.
