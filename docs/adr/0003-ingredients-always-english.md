# Ingredients are always English

Recipes are English, German, or Urdu/Hindi. Only the recipe text follows the Recipe Language (German stays German, Urdu/Hindi becomes Roman Urdu/Hindi). Every Ingredient Line, Food and Unit is English, because Mealie's shopping list merges by Food and the user wants one food list. German and Urdu/Hindi lines are translated during extraction, with the original line kept as `originalText` and as Evidence.

## Considered Options

- German foods with English aliases: rejected by the user. Two foods for one onion breaks shopping-list merging.
