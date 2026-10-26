"""Contract: catalog reads and creation, identical for every MealieGateway."""

import pytest

from mealie_pipeline.errors import MealieHttpError


def test_about_reports_a_version(gateway):
    assert gateway.about().version


def test_whoami_returns_user_and_group_slug(gateway):
    me = gateway.whoami()
    assert me.username
    assert me.group_slug


def test_created_tag_appears_in_catalog_with_id_and_slug(gateway, unique, live_cleanup):
    name = unique("tag")
    tag = gateway.create_tag(name)
    live_cleanup("organizers/tags", tag.id)

    assert tag.id and tag.slug and tag.name == name
    assert name in [t.name for t in gateway.catalog().tags]


def test_created_food_appears_in_catalog(gateway, unique, live_cleanup):
    name = unique("food")
    food = gateway.create_food(name, plural_name=f"{name}s")
    live_cleanup("foods", food.id)

    found = {f.name: f for f in gateway.catalog().foods}
    assert found[name].id == food.id
    assert found[name].plural_name == f"{name}s"


def test_created_unit_without_abbreviation_is_accepted(gateway, unique, live_cleanup):
    name = unique("unit")
    unit = gateway.create_unit(name)
    live_cleanup("units", unit.id)

    found = {u.name: u for u in gateway.catalog().units}
    assert found[name].id == unit.id
    assert found[name].abbreviation == ""


def test_created_unit_keeps_its_abbreviation(gateway, unique, live_cleanup):
    name = unique("unit")
    unit = gateway.create_unit(name, abbreviation="zz")
    live_cleanup("units", unit.id)

    assert {u.name: u for u in gateway.catalog().units}[name].abbreviation == "zz"


def test_wrong_token_is_an_http_error_with_status_401(gateway_factory):
    bad = gateway_factory(token="wrong-token")
    with pytest.raises(MealieHttpError) as err:
        bad.whoami()
    assert err.value.status == 401
