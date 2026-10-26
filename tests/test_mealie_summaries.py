"""`list_recipe_summaries`: the shared contract (fake, local server, opt-in live) plus the HTTP shape."""

import contextlib

import pytest

from mealie_pipeline.adapters.fake_mealie import FakeMealie
from mealie_pipeline.adapters.mealie_http import MealieHttpGateway
from mealie_pipeline.errors import MealieHttpError
from tests.mealie_server import FakeMealieServer


@pytest.fixture
def recipe(gateway, unique):
    slug = gateway.create_recipe(unique("recipe"))
    try:
        yield slug
    finally:
        with contextlib.suppress(MealieHttpError):
            gateway.delete_recipe(slug)


def test_summaries_carry_slug_name_and_source_url(gateway, recipe, unique):
    url = f"https://example.com/{unique('src')}"
    gateway.patch_recipe(recipe, {"orgURL": url})

    mine = [s for s in gateway.list_recipe_summaries() if s["slug"] == recipe]

    assert len(mine) == 1
    assert mine[0]["orgURL"] == url and mine[0]["name"]


def test_summaries_are_listed_in_one_call_with_per_page_minus_one(httpserver):
    server = FakeMealieServer(httpserver, FakeMealie(valid_token="tok"))
    gateway = MealieHttpGateway(httpserver.url_for("").rstrip("/"), "tok", sleep=lambda _s: None)
    gateway.create_recipe("Dal")
    server.requests.clear()

    gateway.list_recipe_summaries()

    assert [(r.method, r.path, r.query) for r in server.requests] == [
        ("GET", "/api/recipes", {"perPage": "-1"})
    ]
