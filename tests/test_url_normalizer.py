import pytest

from mealie_pipeline.url_normalizer import normalize


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ&si=abc&t=30s",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ&feature=share",
        "https://youtu.be/dQw4w9WgXcQ?si=tracking",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "  https://www.youtube.com/watch?v=dQw4w9WgXcQ  ",
    ],
)
def test_youtube_forms_share_one_video_key(url):
    result = normalize(url)

    assert result is not None
    assert result.video_key == "youtube:dQw4w9WgXcQ"
    assert result.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch?v=short",
        "not a url",
        "",
    ],
)
def test_unsupported_urls(url):
    assert normalize(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ&si=abc",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc123&index=4",  # opened from a playlist
        "https://www.youtube.com/watch?list=WL&v=dQw4w9WgXcQ&pp=xyz",
    ],
)
def test_more_youtube_forms_share_one_video_key(url):
    result = normalize(url)

    assert result is not None
    assert result.video_key == "youtube:dQw4w9WgXcQ"
    assert result.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
