"""URL Normalizer: Instagram, Facebook, timestamped YouTube and website links (pure, table-driven)."""

import pytest

from mealie_pipeline.url_normalizer import (
    needs_redirect,
    normalize,
    normalize_list,
    normalize_website,
    resolve,
)

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


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://fb.watch/abc123/", True),
        ("https://www.facebook.com/share/v/1AbCdEf/", True),
        ("https://www.facebook.com/share/r/1AbCdEf/?mibextid=xyz", True),
        ("https://m.facebook.com/share/v/1AbCdEf/", True),
        ("https://www.facebook.com/reel/1234567890123456", False),
        ("https://www.instagram.com/reel/C9xYz12AbCd/", False),
        ("https://youtu.be/dQw4w9WgXcQ", False),
        ("https://example.com/share/v/1", False),
    ],
)
def test_short_and_share_links_are_marked_for_redirect_resolution(url, expected):
    assert needs_redirect(url) is expected


def test_resolve_follows_the_redirect_before_normalizing():
    redirects = {
        "https://fb.watch/abc123/": "https://www.facebook.com/reel/1234567890123456?mibextid=s",
        "https://www.facebook.com/share/v/1AbCdEf/": "https://www.facebook.com/somepage/videos/1234567890123456/",
    }
    expanded: list[str] = []

    def expand(url: str) -> str:
        expanded.append(url)
        return redirects.get(url, url)

    assert resolve("https://fb.watch/abc123/", expand).video_key == "facebook:1234567890123456"  # type: ignore[union-attr]
    assert resolve("https://www.facebook.com/share/v/1AbCdEf/", expand).canonical_url == FB  # type: ignore[union-attr]
    assert resolve(YT, expand).video_key == "youtube:dQw4w9WgXcQ"  # type: ignore[union-attr]
    assert resolve("https://fb.watch/dead/", expand) is None  # the redirect led nowhere useful
    assert expanded == [
        "https://fb.watch/abc123/",
        "https://www.facebook.com/share/v/1AbCdEf/",
        "https://fb.watch/dead/",
    ]


PL = "https://www.youtube.com/playlist?list="


@pytest.mark.parametrize(
    ("url", "key", "canonical", "private"),
    [
        (f"{PL}PLabc123", "youtube:PLabc123", f"{PL}PLabc123", False),
        ("https://m.youtube.com/playlist?list=PLabc123&si=zzz", "youtube:PLabc123", f"{PL}PLabc123", False),
        (f"{YT}&list=PLabc123", "youtube:PLabc123", f"{PL}PLabc123", False),
        (f"{PL}WL", "youtube:WL", f"{PL}WL", True),
        ("https://youtube.com/playlist?list=LL", "youtube:LL", f"{PL}LL", True),
    ],
)
def test_playlist_urls(url, key, canonical, private):
    result = normalize_list(url)

    assert result is not None
    assert (result.list_key, result.canonical_url, result.private) == (key, canonical, private)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/@somechef",
        "https://www.youtube.com/playlist",
        "https://example.com/playlist?list=PLabc123",
        "https://www.instagram.com/some.chef/saved/all-posts/",  # Instagram lists come with ticket 15
        "",
    ],
)
def test_unsupported_list_urls(url):
    assert normalize_list(url) is None
