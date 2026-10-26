"""In-memory MealieGateway that enforces the same rules the real Mealie does.

Rules mirrored here (wayfinder 03 and the live smoke test): PATCH never auto-creates foods or
units and rejects unknown ids, `POST /api/units` rejects a null abbreviation, tokens are checked,
slugs are generated from the name, and recipes are findable by `orgURL`.
"""

import copy
import re
import uuid
from pathlib import Path
from typing import Any

from mealie_pipeline.adapters.mealie import About, Catalog, Food, Recipe, Tag, Unit, WhoAmI
from mealie_pipeline.errors import MealieAuthError, MealieHttpError, MealieUnreachableError

IMAGE_EXTENSIONS = {"jpg", "png", "webp"}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class FakeMealie:
    def __init__(
        self,
        token: str = "fake-token",
        valid_token: str | None = None,
        *,
        base_url: str = "http://fake-mealie:9000",
        version: str = "v3.22.0",
        username: str = "tester",
        group_slug: str = "home",
        tags: list[str] | None = None,
        foods: list[str] | None = None,
        units: list[str] | None = None,
    ):
        self.token = token
        self.valid_token = valid_token if valid_token is not None else token
        self.base_url = base_url
        self.reachable = True
        self.version = version
        self.username = username
        self.group_slug = group_slug
        self.tags: dict[str, Tag] = {}
        self.foods: dict[str, Food] = {}
        self.units: dict[str, Unit] = {}
        self.recipes: dict[str, Recipe] = {}
        self.images: dict[str, bytes | str] = {}
        for name in tags or []:
            self.create_tag(name)
        for name in foods or []:
            self.create_food(name)
        for name in units or []:
            self.create_unit(name)

    # -- guards ---------------------------------------------------------------------------

    def _connect(self) -> None:
        if not self.reachable:
            raise MealieUnreachableError(self.base_url)

    def _auth(self, method: str, path: str) -> None:
        self._connect()
        if self.token != self.valid_token:
            raise MealieAuthError(method, path, 401, '{"detail":"Unauthorized"}', self.token)

    @staticmethod
    def _unprocessable(method: str, path: str, detail: str) -> MealieHttpError:
        return MealieHttpError(method, path, 422, f'{{"detail":"{detail}"}}')

    # -- account --------------------------------------------------------------------------

    def about(self) -> About:
        self._connect()
        return About(version=self.version)

    def whoami(self) -> WhoAmI:
        self._auth("GET", "/api/users/self")
        return WhoAmI(username=self.username, group_slug=self.group_slug)

    # -- catalog --------------------------------------------------------------------------

    def catalog(self) -> Catalog:
        self._auth("GET", "/api/organizers/tags")
        return Catalog(
            tags=list(self.tags.values()), foods=list(self.foods.values()), units=list(self.units.values())
        )

    def create_tag(self, name: str) -> Tag:
        self._auth("POST", "/api/organizers/tags")
        tag = Tag(id=str(uuid.uuid4()), name=name, slug=slugify(name))
        self.tags[tag.id] = tag
        return tag

    def create_food(self, name: str, plural_name: str | None = None) -> Food:
        self._auth("POST", "/api/foods")
        food = Food(id=str(uuid.uuid4()), name=name, plural_name=plural_name or "")
        self.foods[food.id] = food
        return food

    def create_unit(self, name: str, abbreviation: str | None = None) -> Unit:
        return self.post_unit({"name": name, "abbreviation": "" if abbreviation is None else abbreviation})

    def post_unit(self, body: dict[str, Any]) -> Unit:
        """`POST /api/units`: the real endpoint answers 422 when `abbreviation` is null."""
        self._auth("POST", "/api/units")
        if not isinstance(body.get("abbreviation", ""), str):
            raise self._unprocessable("POST", "/api/units", "abbreviation: Input should be a valid string")
        unit = Unit(id=str(uuid.uuid4()), name=body["name"], abbreviation=body.get("abbreviation", ""))
        self.units[unit.id] = unit
        return unit

    # -- recipes --------------------------------------------------------------------------

    def list_recipe_summaries(self) -> list[Recipe]:
        self._auth("GET", "/api/recipes")
        keys = ("id", "slug", "name", "orgURL")
        return [{k: r.get(k) for k in keys} for r in self.recipes.values()]

    def create_recipe(self, name: str) -> str:
        self._auth("POST", "/api/recipes")
        base = slugify(name) or "recipe"
        slug, n = base, 0
        while slug in self.recipes:
            n += 1
            slug = f"{base}-{n}"
        self.recipes[slug] = {
            "id": str(uuid.uuid4()),
            "slug": slug,
            "name": name,
            "orgURL": None,
            "extras": {},
            "tags": [],
            "recipeIngredient": [],
            "recipeInstructions": [],
        }
        return slug

    def _recipe(self, method: str, slug: str) -> Recipe:
        recipe = self.recipes.get(slug)
        if recipe is None:
            raise MealieHttpError(method, f"/api/recipes/{slug}", 404, '{"detail":"Recipe not found"}')
        return recipe

    def get_recipe(self, slug: str) -> Recipe:
        self._auth("GET", f"/api/recipes/{slug}")
        return copy.deepcopy(self._recipe("GET", slug))

    def patch_recipe(self, slug: str, payload: Recipe) -> Recipe:
        path = f"/api/recipes/{slug}"
        self._auth("PATCH", path)
        recipe = self._recipe("PATCH", slug)
        for ingredient in payload.get("recipeIngredient") or []:
            self._check_reference("PATCH", path, "food", ingredient.get("food"), self.foods)
            self._check_reference("PATCH", path, "unit", ingredient.get("unit"), self.units)
        recipe.update(copy.deepcopy(payload))
        return copy.deepcopy(recipe)

    def _check_reference(
        self, method: str, path: str, kind: str, ref: dict[str, Any] | None, known: dict[str, Any]
    ) -> None:
        if ref is not None and ref.get("id") not in known:
            raise MealieHttpError(
                method, path, 500, f'{{"detail":"{kind} id {ref.get("id")} does not exist"}}'
            )

    def delete_recipe(self, slug: str) -> None:
        self._auth("DELETE", f"/api/recipes/{slug}")
        self._recipe("DELETE", slug)
        del self.recipes[slug]
        self.images.pop(slug, None)

    def find_recipe(self, *, item_key: str | None = None, org_url: str | None = None) -> Recipe | None:
        self._auth("GET", "/api/recipes")
        for recipe in self.recipes.values():
            if org_url is not None and recipe.get("orgURL") == org_url:
                return copy.deepcopy(recipe)
            if item_key is not None and (recipe.get("extras") or {}).get("item_key") == item_key:
                return copy.deepcopy(recipe)
        return None

    # -- images ---------------------------------------------------------------------------

    def upload_image(self, slug: str, path: Path) -> None:
        extension = path.suffix.lstrip(".").lower()
        self.put_image(slug, path.read_bytes(), extension)

    def put_image(self, slug: str, data: bytes, extension: str) -> None:
        """`PUT /api/recipes/{slug}/image`: multipart with an `image` file and an `extension` field."""
        self._auth("PUT", f"/api/recipes/{slug}/image")
        self._recipe("PUT", slug)
        if extension not in IMAGE_EXTENSIONS:
            raise self._unprocessable("PUT", f"/api/recipes/{slug}/image", "unsupported extension")
        self.images[slug] = data

    def set_image_from_url(self, slug: str, url: str) -> None:
        self._auth("POST", f"/api/recipes/{slug}/image")
        self._recipe("POST", slug)
        self.images[slug] = url

    def recipe_url(self, slug: str) -> str:
        return f"{self.base_url}/g/{self.group_slug}/r/{slug}"
