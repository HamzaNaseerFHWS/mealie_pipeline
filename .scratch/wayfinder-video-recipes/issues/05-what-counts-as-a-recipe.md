# 05: Which Videos count as recipes?

Type: grilling
Status: resolved
Blocked by: none

## Question

What does the classifier let through?

## Answer

`recipe` and `recipe_partial` (sauces, techniques) both continue. **Drinks and cocktails are recipes.** Restaurants, places to visit, food tours, product ads, eating/review videos and non-food are skipped. Videos with several recipes are split (see "How are multi-recipe Videos handled?"). The user can Override any label in the classification CSV. Target accuracy: ≥ 95 % on `recipe` against a hand-labelled pilot sample.
