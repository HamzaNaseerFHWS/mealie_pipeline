# Ingredients are always English

Recipes are English, German, or Urdu/Hindi. Only the recipe text follows the Recipe Language (German stays German, Urdu/Hindi becomes Roman Urdu/Hindi). Every Ingredient Line, Food and Unit is English, because Mealie's shopping list merges by Food and the user wants one food list. German and Urdu/Hindi lines are translated during extraction, with the original line kept as `originalText` and as Evidence.

## Considered Options

- German foods with English aliases: rejected by the user. Two foods for one onion breaks shopping-list merging.

## Update (ticket 30)

The source's own food name (German "Zwiebel") is now stored as an **alias** on the English Food, never as a Food of its own: one onion stays one Food and shopping lists still merge. Aliases are added by the Parse stage, logged in `reports/created_aliases.csv`, and never added for guessed (fuzzy) matches or for names that read like a choice or list.
