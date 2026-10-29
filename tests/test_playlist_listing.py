"""The pure parts of the yt-dlp playlist listing: entry mapping and "needs a login" errors."""

import pytest

from mealie_pipeline.adapters.video_source import PlaylistEntry, entry_from_flat, is_login_error


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("ERROR: [youtube:tab] WL: This playlist is private", True),
        ("ERROR: [youtube:tab] PLxyz: The playlist does not exist.", True),
        ("ERROR: Sign in to confirm you're not a bot", True),
        ("ERROR: [youtube] abc: Join this channel to get access to members-only content", True),
        ("ERROR: Unable to download webpage: HTTP Error 503", False),
        ("ERROR: [youtube:tab] Incomplete data received", False),
    ],
)
def test_login_errors_are_told_apart_from_other_failures(message, expected):
    assert is_login_error(message) is expected


def test_flat_entries_map_to_playlist_entries():
    assert entry_from_flat(
        {"id": "dQw4w9WgXcQ", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Dal",
         "channel": "Some Chef", "duration": 312.0}
    ) == PlaylistEntry("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Dal", "Some Chef", 312.0)  # fmt: skip
    assert entry_from_flat({"id": "dQw4w9WgXcQ", "uploader": "Chef"}) == PlaylistEntry(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ", None, "Chef", None
    )
    assert entry_from_flat({"title": "[Private video]"}) is None
