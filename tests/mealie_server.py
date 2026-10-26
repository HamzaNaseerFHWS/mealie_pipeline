"""A local HTTP stand-in for Mealie, backed by FakeMealie, served through pytest-httpserver.

It lets the real `MealieHttpGateway` run end to end in CI. It records every request so tests can
assert the exact HTTP shapes (headers, paths, query strings, JSON and multipart bodies).
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pytest_httpserver import HTTPServer
from werkzeug import Request, Response

from mealie_pipeline.adapters.fake_mealie import FakeMealie
from mealie_pipeline.errors import MealieHttpError


@dataclass
class Recorded:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    json: Any = None
    form: dict[str, str] = field(default_factory=dict)
    files: dict[str, bytes] = field(default_factory=dict)


def _json(data: Any, status: int = 200) -> Response:
    return Response(json.dumps(data), status=status, content_type="application/json")


class FakeMealieServer:
    def __init__(self, httpserver: HTTPServer, fake: FakeMealie):
        self.fake = fake
        self.requests: list[Recorded] = []
        self.flaky_failures = 0
        httpserver.expect_request(re.compile(r"^/.*")).respond_with_handler(self._handle)

    def _handle(self, request: Request) -> Response:
        self.requests.append(
            Recorded(
                method=request.method,
                path=request.path,
                query=dict(request.args),
                headers=dict(request.headers),
                json=request.get_json(silent=True),
                form=dict(request.form),
                files={name: f.read() for name, f in request.files.items()},
            )
        )
        auth = request.headers.get("Authorization", "")
        self.fake.token = auth.removeprefix("Bearer ").strip()
        try:
            return self._route(request)
        except MealieHttpError as err:
            return Response(err.body, status=err.status, content_type="application/json")

    def _route(self, request: Request) -> Response:
        fake, method, path = self.fake, request.method, request.path
        body: Any = request.get_json(silent=True)
        if (method, path) == ("GET", "/api/app/about"):
            return _json({"version": fake.about().version})
        if (method, path) == ("GET", "/api/users/self"):
            me = fake.whoami()
            return _json({"username": me.username, "groupSlug": me.group_slug, "admin": me.admin})
        if method == "GET" and path in ("/api/organizers/tags", "/api/foods", "/api/units"):
            return _json({"items": [self._wire(i) for i in self._items(path)]})
        if method == "POST" and path == "/api/organizers/tags":
            return _json(self._wire(fake.create_tag(body["name"])), 201)
        if method == "POST" and path == "/api/foods":
            return _json(self._wire(fake.create_food(body["name"], body.get("pluralName"))), 201)
        if method == "POST" and path == "/api/units":
            return _json(self._wire(fake.post_unit(body)), 201)
        if (method, path) == ("POST", "/api/recipes"):
            return _json(fake.create_recipe(body["name"]), 201)
        if (method, path) == ("GET", "/api/recipes"):
            return self._query_recipes(request.args.get("queryFilter", ""))
        if match := re.fullmatch(r"/api/recipes/([^/]+)/image", path):
            slug = match.group(1)
            if method == "PUT":
                fake.put_image(slug, request.files["image"].read(), request.form["extension"])
            else:
                fake.set_image_from_url(slug, body["url"])
            return _json({"image": "ok"})
        if match := re.fullmatch(r"/api/recipes/([^/]+)", path):
            slug = match.group(1)
            if method == "GET":
                return _json(fake.get_recipe(slug))
            if method == "PATCH":
                return _json(fake.patch_recipe(slug, body))
            if method == "DELETE":
                fake.delete_recipe(slug)
                return _json(slug)
        return _json({"detail": f"no route for {method} {path}"}, 404)

    def _items(self, path: str):
        fake = self.fake
        fake.catalog()  # auth check
        return {
            "/api/organizers/tags": fake.tags,
            "/api/foods": fake.foods,
            "/api/units": fake.units,
        }[path].values()

    @staticmethod
    def _wire(model) -> dict[str, Any]:
        data = model.model_dump()
        if "plural_name" in data:
            data["pluralName"] = data.pop("plural_name")
        return data

    def _query_recipes(self, query_filter: str) -> Response:
        if not query_filter:
            return _json({"items": self.fake.list_recipe_summaries()})
        if m := re.fullmatch(r'org_url="(.*)"', query_filter):
            found = self.fake.find_recipe(org_url=m.group(1))
        elif m := re.fullmatch(r'extras\.key="item_key" AND extras\.value="(.*)"', query_filter):
            found = self.fake.find_recipe(item_key=m.group(1))
        else:
            return _json({"detail": f"unsupported queryFilter {query_filter!r}"}, 400)
        return _json({"items": [found] if found else []})
