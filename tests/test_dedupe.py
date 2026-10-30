"""Ticket 18, the pure part: grouping, canonical choice, overrides and the Jaccard confirmation."""

from datetime import date

import pytest

from mealie_pipeline.dedupe import (
    Candidate,
    candidate,
    confirmed,
    find_groups,
    foods_of,
    has_ingredient_list,
    jaccard,
    parse_date,
    plan_groups,
    read_overrides,
    write_csv,
)

BHINDI = "Chatpata Bhindi Aloo | Crispy Okra Stir Fry"
CAPTION = "Crispy okra and potato.\nIngredients\n250 g okra\n2 onions\n2 tbsp oil"


def cand(key, title=BHINDI, *, handle="yourfoodlab", day=1, website=False, ingredients=False):
    platform = key.split(":")[0]
    return Candidate(key, platform, f"https://{platform}.example/{key}", handle, title,
                     date(2024, 3, day) if day else None, website, ingredients)  # fmt: skip


def groups_of(cands, overrides=None, **kw):
    return [(g.canonical, g.also_on, g.reason) for g in plan_groups(cands, overrides or {}, **kw)]


def test_the_same_reel_on_instagram_and_facebook_is_one_group():
    reel = cand("instagram:A", "Chatpata Bhindi Aloo #okra", handle="yourfoodlab", ingredients=True)
    copy = cand("facebook:1", "Chatpata Bhindi Aloo #okra", handle="yourfoodlabs", day=2)

    assert groups_of([copy, reel]) == [("instagram:A", ("facebook:1",), "richest source")]


def test_a_youtube_short_and_the_long_video_are_one_group_and_the_website_wins():
    short = cand("youtube:SHORT0000AA", BHINDI + " #shorts")
    long = cand("youtube:LONG00000BB", BHINDI, website=True, day=3)

    assert groups_of([short, long]) == [("youtube:LONG00000BB", ("youtube:SHORT0000AA",), "richest source")]


def test_two_different_recipes_by_the_same_creator_on_the_same_day_are_not_merged():
    dal = cand("youtube:DAL00000000", "Tadka Dal Fry | Easy Lentil Curry")

    assert find_groups([cand("youtube:BHINDI00000"), dal]) == []


def test_videos_by_different_creators_or_far_apart_in_time_are_not_merged():
    assert find_groups([cand("youtube:AAAAAAAAAAA"), cand("instagram:B", handle="someoneelse")]) == []
    assert find_groups([cand("youtube:AAAAAAAAAAA", day=1), cand("instagram:B", day=20)]) == []
    assert find_groups([cand("youtube:AAAAAAAAAAA", handle=""), cand("instagram:B", handle="")]) == []


def test_a_missing_upload_date_does_not_block_a_match():
    assert len(find_groups([cand("youtube:AAAAAAAAAAA"), cand("facebook:1", day=0)])) == 1


@pytest.mark.parametrize(
    ("members", "winner"),
    [
        ([cand("instagram:A"), cand("youtube:YYYYYYYYYYY")], "youtube:YYYYYYYYYYY"),  # YouTube > others
        ([cand("youtube:YYYYYYYYYYY"), cand("instagram:A", ingredients=True)], "instagram:A"),
        ([cand("instagram:A", ingredients=True), cand("facebook:1", website=True)], "facebook:1"),
        ([cand("instagram:A"), cand("facebook:1")], "facebook:1"),  # a tie takes the lowest key
    ],
)
def test_the_canonical_video_has_the_richest_source(members, winner):
    ((canonical, _, _),) = groups_of(members)
    assert canonical == winner


def test_a_video_already_in_mealie_stays_canonical_even_against_a_richer_source():
    reel = cand("instagram:A")
    long = cand("youtube:YYYYYYYYYYY", website=True)

    assert groups_of([reel, long], existing=frozenset({"instagram:A"})) == [
        ("instagram:A", ("youtube:YYYYYYYYYYY",), "existing")
    ]


def test_a_video_that_already_went_on_stays_canonical():
    first = cand("instagram:A")
    richer = cand("youtube:YYYYYYYYYYY", website=True)

    ((canonical, _, reason),) = groups_of([first, richer], settled=frozenset({"instagram:A"}))
    assert (canonical, reason) == ("instagram:A", "settled")


def test_override_split_lets_both_videos_proceed():
    a, b = cand("youtube:AAAAAAAAAAA"), cand("instagram:B")

    assert groups_of([a, b], {"instagram:B": "split"}) == []
    assert groups_of([a, b], {"youtube:AAAAAAAAAAA": "split"}) == []


def test_override_canonical_wins_over_the_richer_source():
    a, b = cand("youtube:AAAAAAAAAAA", website=True), cand("instagram:B")

    assert groups_of([a, b], {"instagram:B": "canonical"}) == [
        ("instagram:B", ("youtube:AAAAAAAAAAA",), "override")
    ]


def test_a_split_video_leaves_a_three_way_group_without_breaking_it():
    a, b, c = cand("youtube:AAAAAAAAAAA"), cand("instagram:B"), cand("facebook:1")

    assert groups_of([a, b, c], {"facebook:1": "split"}) == [
        ("youtube:AAAAAAAAAAA", ("instagram:B",), "richest source")
    ]


def test_jaccard_confirmation_needs_seventy_percent_of_the_foods():
    base = foods_of(["Okra", "Onion", "Salt", "Cumin", "Oil"])
    assert jaccard(base, base) == 1.0
    assert confirmed(base, foods_of(["okra", "onion", "salt", "cumin", "oil", "chilli"]))  # 5/6
    assert not confirmed(base, foods_of(["okra", "onion", "rice"]))  # 2/6
    assert jaccard(set(), set()) == 0.0


def test_ingredient_list_detection():
    assert has_ingredient_list(CAPTION)
    assert has_ingredient_list("250 g okra\n2 onions\n3 tbsp oil")
    assert not has_ingredient_list("So good! Recipe in bio.")


def test_candidate_reads_website_and_ingredients_from_the_caption():
    c = candidate(
        "instagram:A",
        "instagram",
        "u",
        handle="x",
        title="",
        description=CAPTION + "\nhttps://chef.example/r",
        upload_date="20240301",
    )
    assert (c.has_website, c.has_ingredient_list, c.upload_date, c.title) == (
        True, True, date(2024, 3, 1), "Crispy okra and potato.",
    )  # fmt: skip
    assert parse_date("garbage") is None and parse_date(None) is None


def test_overrides_are_read_from_the_csv_and_unknown_values_warn(tmp_path):
    path = write_csv(tmp_path / "dedupe.csv", [])
    assert read_overrides(path) == ({}, [])
    path.write_text(
        "group_id,video_key,override\ng,instagram:A,SPLIT\ng,facebook:1,merge\ng,x,\n", encoding="utf-8"
    )

    overrides, warnings = read_overrides(path)

    assert overrides == {"instagram:A": "split"}
    assert len(warnings) == 1 and "facebook:1" in warnings[0]
    assert read_overrides(tmp_path / "missing.csv") == ({}, [])
