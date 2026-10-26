"""Gateway fixtures: the same contract scenarios run against every implementation."""

import os
import uuid
from collections.abc import Callable, Iterator

import pytest

from mealie_pipeline.adapters.fake_mealie import FakeMealie
from mealie_pipeline.adapters.mealie import MealieGateway
from mealie_pipeline.adapters.mealie_http import MealieHttpGateway
from tests.mealie_server import FakeMealieServer

TOKEN = "test-token-1234567890"

GatewayFactory = Callable[..., MealieGateway]


@pytest.fixture
def unique() -> Callable[[str], str]:
    """Unique `zz-it-<prefix>-<uuid>` names, so live runs never collide with real data."""

    def make(prefix: str = "item") -> str:
        return f"zz-it-{prefix}-{uuid.uuid4().hex[:8]}"

    return make


@pytest.fixture(params=["fake", "http", pytest.param("live", marks=pytest.mark.mealie_live)])
def gateway_factory(request, httpserver) -> GatewayFactory:
    """Builds a gateway of the parametrised kind; `token` overrides the credential."""
    kind = request.param
    served: list[bool] = []

    def build(token: str | None = None) -> MealieGateway:
        if kind == "fake":
            return FakeMealie(token=token or TOKEN, valid_token=TOKEN)
        if kind == "http":
            if not served:
                FakeMealieServer(httpserver, FakeMealie(valid_token=TOKEN))
                served.append(True)
            return MealieHttpGateway(
                httpserver.url_for("").rstrip("/"), token or TOKEN, sleep=lambda _s: None
            )
        url, live_token = os.environ.get("MEALIE_IT_URL"), os.environ.get("MEALIE_IT_TOKEN")
        if not url or not live_token:
            pytest.skip("set MEALIE_IT_URL and MEALIE_IT_TOKEN to run the live contract suite")
        return MealieHttpGateway(url, token or live_token)

    return build


@pytest.fixture
def gateway(gateway_factory: GatewayFactory) -> MealieGateway:
    return gateway_factory()


@pytest.fixture
def live_cleanup(request, gateway: MealieGateway) -> Iterator[Callable[[str, str], None]]:
    """Registers catalog entries to delete afterwards, on the live instance only.

    The fake and the local server start empty for every test, so nothing needs removing there.
    """
    pending: list[tuple[str, str]] = []
    yield lambda kind, item_id: pending.append((kind, item_id))
    if request.node.callspec.params.get("gateway_factory") == "live" and isinstance(
        gateway, MealieHttpGateway
    ):
        for kind, item_id in reversed(pending):
            gateway.delete_catalog_entry(kind, item_id)
