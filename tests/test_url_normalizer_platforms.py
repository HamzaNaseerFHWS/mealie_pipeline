"""URL Normalizer: Instagram, Facebook, timestamped YouTube and website links (pure, table-driven)."""

import pytest

from mealie_pipeline.url_normalizer import normalize, normalize_website

IG = "https://www.instagram.com/p/C9xYz12AbCd/"
FB = "https://www.facebook.com/watch/?v=1234567890123456"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize(
    ("url", "key", "canonical"),
    [
        ("https://www.instagram.com/reel/C9xYz12AbCd/?igsh=MWx0b2Z", "instagram:C9xYz12AbCd", IG),
        ("https://instagram.com/reel/C9xYz12AbCd", "instagram:C9xYz12AbCd", IG),
        ("https://www.instagram.com/p/C9xYz12AbCd/", "instagram:C9xYz12AbCd", IG),
        ("https://www.instagram.com/reels/C9xYz12AbCd/", "instagram:C9xYz12AbCd", IG),
        (
            "https://www.instagram.com/tv/C9xYz12AbCd/?utm_source=ig_web_copy_link",
            "instagram:C9xYz12AbCd",
            IG,
        ),
        ("https://m.instagram.com/p/C9xYz12AbCd/?utm_medium=share_sheet", "instagram:C9xYz12AbCd", IG),
        ("https://www.instagram.com/some.chef/reel/C9xYz12AbCd/", "instagram:C9xYz12AbCd", IG),
        ("https://www.facebook.com/reel/1234567890123456?mibextid=abc", "facebook:1234567890123456", FB),
        ("https://www.facebook.com/watch/?v=1234567890123456&fbclid=zzz", "facebook:1234567890123456", FB),
        ("https://m.facebook.com/watch?v=1234567890123456", "facebook:1234567890123456", FB),
        ("https://www.facebook.com/somepage/videos/1234567890123456/", "facebook:1234567890123456", FB),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=95s", "youtube:dQw4w9WgXcQ", YT),
    ],
)
def test_video_url_forms(url, key, canonical):
    result = normalize(url)

    assert result is not None
    assert (result.video_key, result.canonical_url) == (key, canonical)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/some.chef/",
        "https://www.instagram.com/explore/tags/okra/",
        "https://www.facebook.com/somepage/",
        "https://fb.watch/abc123/",  # a short link: the caller resolves the redirect first
    ],
)
def test_profile_and_short_links_are_not_videos(url):
    assert normalize(url) is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.example.com/recipes/dal/", "example.com/recipes/dal"),
        ("http://example.com/recipes/dal", "example.com/recipes/dal"),
        ("https://example.com/recipes/dal?utm_source=x&utm_medium=y", "example.com/recipes/dal"),
        ("https://example.com/recipes/dal?fbclid=1#comments", "example.com/recipes/dal"),
        ("https://m.example.com//recipes//dal/", "example.com/recipes/dal"),
        ("https://Example.com/Recipes/Dal", "example.com/Recipes/Dal"),  # only the host is case-folded
        ("https://example.com/recipe?id=7&utm_campaign=z", "example.com/recipe?id=7"),
        ("example.com/recipes/dal", "example.com/recipes/dal"),
        ("https://example.com/", "example.com"),
        ("", None),
        ("   ", None),
        ("not a url", None),
        ("ftp://example.com/x", None),
        ("https://localhost/x", None),
    ],
)
def test_normalize_website(url, expected):
    assert normalize_website(url) == expected
