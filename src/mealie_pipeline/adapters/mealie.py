"""The MealieGateway port: everything the pipeline needs from Mealie, and nothing more.

Mealie is storage plus tag/food/unit lookup (ADR 0001). Never call `POST /api/recipes/create/*`
or `/api/parser/*`, and always PATCH, never PUT, on recipes.
"""

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field


class About(BaseModel):
    version: str


class WhoAmI(BaseModel):
    username: str
    group_slug: str
    full_name: str = ""
    admin: bool = False


class Tag(BaseModel):
    id: str
    name: str
    slug: str


class Food(BaseModel):
    id: str
    name: str
    plural_name: str = ""
    aliases: list[str] = Field(default_factory=list)


class Unit(BaseModel):
    id: str
    name: str
    abbreviation: str = ""
    plural_name: str = ""


class Catalog(BaseModel):
    tags: list[Tag] = Field(default_factory=list)
    foods: list[Food] = Field(default_factory=list)
    units: list[Unit] = Field(default_factory=list)


Recipe = dict[str, Any]


class MealieGateway(Protocol):
    def about(self) -> About: ...

    def whoami(self) -> WhoAmI: ...

    def catalog(self) -> Catalog: ...

    def create_food(self, name: str, plural_name: str | None = None) -> Food: ...

    def create_unit(self, name: str, abbreviation: str | None = None) -> Unit: ...

    def create_tag(self, name: str) -> Tag: ...

    def find_recipe(self, *, item_key: str | None = None, org_url: str | None = None) -> Recipe | None:
        """The full recipe whose `extras.item_key` or `orgURL` matches, or None."""
        ...

    def list_recipe_summaries(self) -> list[Recipe]:
        """Every recipe's summary (`slug`, `name`, `orgURL`, ...) in one call (`perPage=-1`)."""
        ...

    def create_recipe(self, name: str) -> str:
        """Creates an empty recipe and returns its slug."""
        ...

    def patch_recipe(self, slug: str, payload: Recipe) -> Recipe:
        """Changes only the camelCase fields sent. Ingredient food/unit ids must already exist."""
        ...

    def get_recipe(self, slug: str) -> Recipe: ...

    def upload_image(self, slug: str, path: Path) -> None:
        """Uploads an image file (jpg, png or webp)."""
        ...

    def set_image_from_url(self, slug: str, url: str) -> None:
        """Has Mealie download the image itself."""
        ...

    def delete_recipe(self, slug: str) -> None: ...

    def recipe_url(self, slug: str) -> str:
        """`<MEALIE_URL>/g/<group_slug>/r/<slug>`, for reports."""
        ...
