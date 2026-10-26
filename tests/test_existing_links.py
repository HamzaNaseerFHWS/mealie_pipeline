"""The Existing Link Set: real-looking `orgURL` variants map to the keys the pipeline asks for."""

import pytest

from mealie_pipeline.existing_links import build_link_set, link_key


@pytest.mark.parametrize(
    ("org_url", "key"),
    [
        ("https://www.instagram.com/reel/ABCdef12345/?igsh=MWx0", "instagram:ABCdef12345"),
        ("https://www.instagram.com/p/ABCdef12345/", "instagram:ABCdef12345"),
        ("https://www.instagram.com/reels/ABCdef12345", "instagram:ABCdef12345"),
        ("https://m.instagram.com/reel/ABCdef12345/?utm_source=ig_web_copy_link", "instagram:ABCdef12345"),
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "youtube:dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube:dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=95s", "youtube:dQw4w9WgXcQ"),  # multi-recipe part
        ("https://www.facebook.com/reel/1234567890123456?mibextid=x", "facebook:1234567890123456"),
        ("https://www.facebook.com/watch/?v=1234567890123456", "facebook:1234567890123456"),
        ("https://www.mysite.com/recipes/dal/", "mysite.com/recipes/dal"),
        ("http://mysite.com/recipes/dal?utm_source=newsletter", "mysite.com/recipes/dal"),
        ("", None),
        (None, None),
        (42, None),
        ("garbage value", None),
    ],
)
def test_link_key(org_url, key):
    assert link_key(org_url) == key


def test_the_set_maps_every_variant_of_one_video_to_its_recipe():
    summaries = [
        {"slug": "reel-dal", "name": "Dal", "orgURL": "https://www.instagram.com/reel/ABCdef12345/?igsh=1"},
        {"slug": "web-dal", "name": "Dal 2", "orgURL": "https://www.mysite.com/dal/"},
        {"slug": "no-link", "name": "Handwritten", "orgURL": None},
        {"slug": "junk", "name": "Junk", "orgURL": "n/a"},
        {"slug": "", "name": "No slug", "orgURL": "https://youtu.be/dQw4w9WgXcQ"},
    ]

    links = build_link_set(summaries)

    assert links == {"instagram:ABCdef12345": "reel-dal", "mysite.com/dal": "web-dal"}
    assert links[link_key("https://instagram.com/p/ABCdef12345/") or ""] == "reel-dal"


def test_the_first_recipe_wins_a_shared_key():
    links = build_link_set(
        [
            {"slug": "first", "orgURL": "https://youtu.be/dQw4w9WgXcQ"},
            {"slug": "second", "orgURL": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s"},
        ]
    )

    assert links == {"youtube:dQw4w9WgXcQ": "first"}


def test_names_are_never_matched():
    assert build_link_set([{"slug": "dal", "name": "Chatpata Bhindi Aloo", "orgURL": None}]) == {}
