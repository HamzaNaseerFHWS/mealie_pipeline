"""MealieHttpGateway against a local server: exact HTTP shapes, errors, retries, token safety."""

import json

import httpx
import pytest

from mealie_pipeline.adapters.fake_mealie import FakeMealie
from mealie_pipeline.adapters.mealie_http import MealieHttpGateway
from mealie_pipeline.errors import MealieAuthError, MealieHttpError, MealieUnreachableError
from tests.mealie_server import FakeMealieServer

TOKEN = "secret-token-abcdef123456"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 8


@pytest.fixture
def server(httpserver):
    return FakeMealieServer(httpserver, FakeMealie(valid_token=TOKEN))


@pytest.fixture
def gateway(server, httpserver):
    return MealieHttpGateway(httpserver.url_for("").rstrip("/"), TOKEN, sleep=lambda _s: None)


def last(server):
    return server.requests[-1]


def test_requests_carry_the_bearer_token(server, gateway):
    gateway.whoami()
    assert last(server).headers["Authorization"] == f"Bearer {TOKEN}"
    assert (last(server).method, last(server).path) == ("GET", "/api/users/self")


def test_catalog_lists_with_per_page_minus_one(server, gateway):
    gateway.catalog()
    listing = {r.path: r.query for r in server.requests}
    for path in ("/api/organizers/tags", "/api/foods", "/api/units"):
        assert listing[path] == {"perPage": "-1"}


def test_create_recipe_posts_the_name_and_returns_the_slug(server, gateway):
    slug = gateway.create_recipe("Chatpata Bhindi")
    assert slug == "chatpata-bhindi"
    assert (last(server).method, last(server).path, last(server).json) == (
        "POST",
        "/api/recipes",
        {"name": "Chatpata Bhindi"},
    )


def test_patch_uses_patch_and_sends_camel_case_keys_including_org_url(server, gateway):
    slug = gateway.create_recipe("Dal")
    gateway.patch_recipe(slug, {"orgURL": "https://youtu.be/x", "recipeServings": 2})
    assert (last(server).method, last(server).path) == ("PATCH", f"/api/recipes/{slug}")
    assert last(server).json == {"orgURL": "https://youtu.be/x", "recipeServings": 2}
    assert not any(r.method == "PUT" and r.path == f"/api/recipes/{slug}" for r in server.requests)


def test_find_by_org_url_sends_a_snake_case_query_filter(server, gateway):
    gateway.find_recipe(org_url="https://youtu.be/x")
    assert last(server).query == {"queryFilter": 'org_url="https://youtu.be/x"'}


def test_upload_image_is_multipart_with_image_file_and_extension_field(server, gateway, tmp_path):
    slug = gateway.create_recipe("Dal")
    image = tmp_path / "cover.png"
    image.write_bytes(PNG)
    gateway.upload_image(slug, image)
    sent = last(server)
    assert (sent.method, sent.path) == ("PUT", f"/api/recipes/{slug}/image")
    assert sent.headers["Content-Type"].startswith("multipart/form-data")
    assert sent.files == {"image": PNG}
    assert sent.form == {"extension": "png"}


def test_set_image_from_url_posts_the_url(server, gateway):
    slug = gateway.create_recipe("Dal")
    gateway.set_image_from_url(slug, "https://img.example/x.jpg")
    assert (last(server).method, last(server).path, last(server).json) == (
        "POST",
        f"/api/recipes/{slug}/image",
        {"url": "https://img.example/x.jpg"},
    )


def test_unit_without_abbreviation_sends_an_empty_string_never_null(server, gateway):
    gateway.create_unit("handful")
    assert last(server).json == {"name": "handful", "abbreviation": ""}


def test_non_2xx_raises_a_typed_error_with_method_path_status_and_body(gateway):
    with pytest.raises(MealieHttpError) as err:
        gateway.get_recipe("missing")
    assert (err.value.method, err.value.path, err.value.status) == ("GET", "/api/recipes/missing", 404)
    assert "Recipe not found" in err.value.body


def test_error_body_is_truncated_to_2000_chars(httpserver):
    httpserver.expect_request("/api/recipes/x").respond_with_data("e" * 5000, status=500)
    gw = MealieHttpGateway(httpserver.url_for("").rstrip("/"), TOKEN, sleep=lambda _s: None)
    with pytest.raises(MealieHttpError) as err:
        gw.get_recipe("x")
    assert len(err.value.body) == 2000


def test_token_is_redacted_from_error_bodies_and_messages(httpserver):
    httpserver.expect_request("/api/users/self").respond_with_data(f"echo {TOKEN} echo", status=500)
    gw = MealieHttpGateway(httpserver.url_for("").rstrip("/"), TOKEN, sleep=lambda _s: None)
    with pytest.raises(MealieHttpError) as err:
        gw.whoami()
    assert TOKEN not in err.value.body
    assert TOKEN not in str(err.value)


def test_401_is_reported_as_an_invalid_token(httpserver):
    gw = MealieHttpGateway(httpserver.url_for("").rstrip("/"), TOKEN, sleep=lambda _s: None)
    httpserver.expect_request("/api/users/self").respond_with_data("nope", status=401)
    with pytest.raises(MealieAuthError) as err:
        gw.whoami()
    assert "token invalid" in str(err.value)
    assert TOKEN not in str(err.value)


def test_unreachable_server_retries_three_times_then_explains_tailscale():
    sleeps: list[float] = []
    attempts: list[int] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ConnectError("name resolution failed", request=request)

    gw = MealieHttpGateway("http://mealie.invalid:9000", TOKEN, backoff=0.5, sleep=sleeps.append)
    gw._client = httpx.Client(base_url=gw.base_url, transport=httpx.MockTransport(refuse))
    with pytest.raises(MealieUnreachableError) as err:
        gw.about()
    assert len(attempts) == 4  # first try plus three retries
    assert sleeps == [0.5, 1.0, 2.0]
    assert "cannot reach Mealie at http://mealie.invalid:9000: is Tailscale connected?" in str(err.value)


def test_a_connection_error_followed_by_success_is_retried_transparently():
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("blip", request=request)
        return httpx.Response(200, content=json.dumps({"version": "v3.22.0"}))

    gw = MealieHttpGateway("http://mealie:9000", TOKEN, sleep=lambda _s: None)
    gw._client = httpx.Client(base_url=gw.base_url, transport=httpx.MockTransport(flaky))
    assert gw.about().version == "v3.22.0"
    assert calls["n"] == 2
