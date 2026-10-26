"""Table tests for thumbnail selection (the fallback logic) and image header parsing."""

import pytest

from mealie_pipeline.adapters.downloader import FakeImageDownloader
from mealie_pipeline.images import candidate_urls, image_info, pick_image
from tests.images import make_jpeg, make_png

MAX = "https://i.ytimg.com/vi/abc/maxresdefault.jpg"
HQ = "https://i.ytimg.com/vi/abc/hqdefault.jpg"


def test_youtube_candidates_are_maxres_then_hq():
    assert candidate_urls("youtube", "abc", "ignored") == [MAX, HQ]


def test_other_platforms_use_the_metadata_thumbnail():
    assert candidate_urls("instagram", "abc", "https://cdn/x.jpg") == ["https://cdn/x.jpg"]
    assert candidate_urls("instagram", "abc", None) == []


@pytest.mark.parametrize(
    ("files", "expected_url"),
    [
        ({MAX: make_jpeg(1280), HQ: make_jpeg(480)}, MAX),
        ({HQ: make_jpeg(480)}, HQ),  # maxres is a 404
        ({MAX: make_jpeg(120), HQ: make_jpeg(480)}, HQ),  # maxres is the 120px placeholder
        ({MAX: b"<html>not an image</html>", HQ: make_png(640)}, HQ),
        ({MAX: make_jpeg(120), HQ: make_jpeg(100)}, None),
        ({}, None),
    ],
)
def test_pick_image(files, expected_url):
    picked = pick_image([MAX, HQ], FakeImageDownloader(files))

    assert (picked.url if picked else None) == expected_url


def test_pick_image_reports_the_file_extension():
    picked = pick_image([HQ], FakeImageDownloader({HQ: make_png(640)}))

    assert picked is not None and picked.extension == "png"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (make_jpeg(1280), ("jpg", 1280)),
        (make_png(300), ("png", 300)),
        (b"GIF89a....", None),
        (b"", None),
    ],
)
def test_image_info(data, expected):
    assert image_info(data) == expected
