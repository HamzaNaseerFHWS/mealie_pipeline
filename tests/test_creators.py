"""Creator handles (pure): the same Creator on YouTube, Instagram and Facebook gets one key."""

import pytest

from mealie_pipeline.creators import creator_handle
from mealie_pipeline.models import VideoMeta


@pytest.mark.parametrize(
    ("meta", "handle"),
    [
        (
            VideoMeta(title="t", uploader="Your Food Lab", uploader_id="@yourfoodlab"),
            "yourfoodlab",
        ),  # YouTube
        # Instagram: uploader_id is the numeric account id, `channel` the username
        (
            VideoMeta(title="t", uploader="Your Food Lab", uploader_id="2815873", channel="yourfoodlab"),
            "yourfoodlab",
        ),
        (
            VideoMeta(title="t", uploader="Spice Kitchen", uploader_id="UCq9x8LmN3oPq7rS2tU5vW1x"),
            "spicekitchen",
        ),
        (VideoMeta(title="t", uploader="Oma's Küche", uploader_id="omas.kueche"), "omaskueche"),
        (VideoMeta(title="t"), ""),
    ],
)
def test_creator_handle(meta, handle):
    assert creator_handle(meta) == handle


def test_one_website_is_shared_across_platforms_and_the_first_one_learned_wins(tmp_path):
    from mealie_pipeline.creators import CreatorRegistry
    from mealie_pipeline.store import StateStore

    registry = CreatorRegistry(StateStore(tmp_path / "pipeline.db"))
    youtube = creator_handle(VideoMeta(title="t", uploader="Your Food Lab", uploader_id="@yourfoodlab"))
    instagram = creator_handle(VideoMeta(title="t", uploader_id="2815873", channel="yourfoodlab"))

    assert registry.learn(youtube, "https://foodlab.example", "video", "youtube:A")
    assert not registry.learn(instagram, "https://other.example", "bio", "instagram:B")  # not overwritten

    assert registry.website(instagram) == "https://foodlab.example"
    assert registry.website("") is None
