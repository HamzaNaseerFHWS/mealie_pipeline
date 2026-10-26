"""The real MealieGateway over httpx. Follows wayfinder ticket 03 and the live findings in ticket 01."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from mealie_pipeline.adapters.mealie import About, Catalog, Food, Recipe, Tag, Unit, WhoAmI
from mealie_pipeline.errors import (
    MealieAuthError,
    MealieHttpError,
    MealieUnreachableError,
    redact,
)

IMAGE_MIME = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


class MealieHttpGateway:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
        backoff: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._max_retries = max_retries
        self._backoff = backoff
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        self._group_slug: str | None = None

    # -- transport ------------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Sends a request, retrying connection errors with backoff; raises typed errors."""
        last: httpx.TransportError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.request(method, path, **kwargs)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as err:
                last = err
                if attempt < self._max_retries:
                    self._sleep(self._backoff * 2**attempt)
        else:
            raise MealieUnreachableError(self.base_url, redact(str(last), self._token)) from last
        if response.is_success:
            return response
        if response.status_code == 401:
            raise MealieAuthError(method, path, 401, response.text, self._token)
        raise MealieHttpError(method, path, response.status_code, response.text, self._token)

    def _items(self, path: str) -> list[dict[str, Any]]:
        return self._request("GET", path, params={"perPage": -1}).json()["items"]

    # -- account --------------------------------------------------------------------------

    def about(self) -> About:
        return About(version=self._request("GET", "/api/app/about").json()["version"])

    def whoami(self) -> WhoAmI:
        data = self._request("GET", "/api/users/self").json()
        self._group_slug = data["groupSlug"]
        return WhoAmI(
            username=data["username"],
            group_slug=data["groupSlug"],
            full_name=data.get("fullName") or "",
            admin=bool(data.get("admin")),
        )

    # -- catalog --------------------------------------------------------------------------

    def catalog(self) -> Catalog:
        return Catalog(
            tags=[
                Tag(id=t["id"], name=t["name"], slug=t["slug"]) for t in self._items("/api/organizers/tags")
            ],
            foods=[
                Food(id=f["id"], name=f["name"], plural_name=f.get("pluralName") or "")
                for f in self._items("/api/foods")
            ],
            units=[
                Unit(
                    id=u["id"],
                    name=u["name"],
                    abbreviation=u.get("abbreviation") or "",
                    plural_name=u.get("pluralName") or "",
                )
                for u in self._items("/api/units")
            ],
        )

    def create_tag(self, name: str) -> Tag:
        data = self._request("POST", "/api/organizers/tags", json={"name": name}).json()
        return Tag(id=data["id"], name=data["name"], slug=data["slug"])

    def create_food(self, name: str, plural_name: str | None = None) -> Food:
        body: dict[str, Any] = {"name": name}
        if plural_name:
            body["pluralName"] = plural_name
        data = self._request("POST", "/api/foods", json=body).json()
        return Food(id=data["id"], name=data["name"], plural_name=data.get("pluralName") or "")

    def create_unit(self, name: str, abbreviation: str | None = None) -> Unit:
        # Mealie answers 422 to a null abbreviation, so a missing one is sent as "".
        body = {"name": name, "abbreviation": "" if abbreviation is None else abbreviation}
        data = self._request("POST", "/api/units", json=body).json()
        return Unit(id=data["id"], name=data["name"], abbreviation=data.get("abbreviation") or "")

    def delete_catalog_entry(self, kind: str, item_id: str) -> None:
        """Test cleanup only (`organizers/tags`, `foods` or `units`); the pipeline never deletes these."""
        self._request("DELETE", f"/api/{kind}/{item_id}")

    # -- recipes --------------------------------------------------------------------------

    def create_recipe(self, name: str) -> str:
        return self._request("POST", "/api/recipes", json={"name": name}).json()

    def get_recipe(self, slug: str) -> Recipe:
        return self._request("GET", f"/api/recipes/{slug}").json()

    def patch_recipe(self, slug: str, payload: Recipe) -> Recipe:
        return self._request("PATCH", f"/api/recipes/{slug}", json=payload).json()

    def delete_recipe(self, slug: str) -> None:
        self._request("DELETE", f"/api/recipes/{slug}")

    def find_recipe(self, *, item_key: str | None = None, org_url: str | None = None) -> Recipe | None:
        if org_url is not None:
            query = f'org_url="{org_url}"'
        elif item_key is not None:
            query = f'extras.key="item_key" AND extras.value="{item_key}"'
        else:
            raise ValueError("find_recipe needs item_key or org_url")
        items = self._request("GET", "/api/recipes", params={"queryFilter": query}).json()["items"]
        return self.get_recipe(items[0]["slug"]) if items else None

    # -- images ---------------------------------------------------------------------------

    def upload_image(self, slug: str, path: Path) -> None:
        extension = path.suffix.lstrip(".").lower()
        files = {
            "image": (path.name, path.read_bytes(), IMAGE_MIME.get(extension, "application/octet-stream"))
        }
        self._request("PUT", f"/api/recipes/{slug}/image", files=files, data={"extension": extension})

    def set_image_from_url(self, slug: str, url: str) -> None:
        self._request("POST", f"/api/recipes/{slug}/image", json={"url": url})

    def recipe_url(self, slug: str) -> str:
        if self._group_slug is None:
            self.whoami()
        return f"{self.base_url}/g/{self._group_slug}/r/{quote(slug)}"
