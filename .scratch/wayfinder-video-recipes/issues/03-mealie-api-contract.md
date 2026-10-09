# 03: What exactly does Mealie's API require to store a fully parsed, tagged recipe?

Type: research
Status: resolved
Blocked by: none

## Question

Which endpoints and payload rules does the uploader need, given Mealie v3.28.0 source?

## Answer

From the Mealie source (`mealie-recipes/mealie` @ `96f15f3`, v3.28.0):

- Auth: `Authorization: Bearer <token>`. Tokens are made in the UI at *Profile → API Tokens* (`/user/profile/api-tokens`) or via `POST /api/users/api-tokens`. `GET /api/users/self` validates a token. `GET /api/app/about` needs no auth and returns `version`.
- Catalog: `GET /api/organizers/tags?perPage=-1`, `GET /api/foods?perPage=-1`, `GET /api/units?perPage=-1` return `{items: [...]}`. Create with `POST /api/organizers/tags`, `POST /api/foods`, `POST /api/units`.
- Create: `POST /api/recipes {"name": ...}` returns the slug (string, 201). Fill with `PATCH /api/recipes/{slug}` (only the fields sent are changed). Read back with `GET /api/recipes/{slug}`. Delete with `DELETE /api/recipes/{slug}`.
- **PATCH/PUT do not create missing foods or units** (only the zip importer does). Every ingredient's `food` and `unit` must reference an existing `id`.
- Ingredient shape: `{quantity, unit:{id,name}, food:{id,name}, note, originalText, title, referenceId}`. `title` on the first ingredient of a Section is the section header.
- Steps: `recipeInstructions: [{id?, title, summary, text, ingredientReferences:[{referenceId}]}]`.
- Tags on a recipe: `tags: [{id, name, slug}]`.
- `orgURL` is the source URL field (camelCase alias in JSON). `extras` is a free-form dict.
- Search by source: `GET /api/recipes?queryFilter=org_url="<url>"`. The query filter decamelizes names, so it needs the **snake_case** column name.
- Image: `PUT /api/recipes/{slug}/image` (multipart upload) or `POST /api/recipes/{slug}/image {"url": ...}`.
- Cleanup helpers: `GET /api/foods/empty`, `GET /api/organizers/tags/empty`, `PUT /api/foods/merge`.

These are verified against the live instance by ticket "Run the Mealie API check on the laptop".
