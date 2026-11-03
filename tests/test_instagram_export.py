"""Instagram data export: saved posts become a Saved List without any login."""

import json
from pathlib import Path

from typer.testing import CliRunner

from mealie_pipeline.cli import app
from mealie_pipeline.instagram_export import UNCOLLECTED, read_export
from mealie_pipeline.store import StateStore
from tests.helpers import fake_adapters


def _post(code: str, caption: str, owner: str = "chef") -> dict:
    return {
        "timestamp": 1793388496,
        "label_values": [
            {
                "label": "URL",
                "value": f"https://www.instagram.com/reel/{code}/",
                "href": f"https://www.instagram.com/reel/{code}/",
            },
            {"label": "Caption", "value": caption},
            {"dict": [{"dict": [{"label": "Username", "value": owner}], "title": ""}], "title": "Owner"},
        ],
    }


def _export(folder: Path) -> None:
    folder.mkdir()
    (folder / "saved_posts.json").write_text(
        json.dumps(
            [_post("AAAAA1", "Pasta\n200 g pasta ð\x9f¥³"), _post("BBBBB2", "Gym"), _post("CCCCC3", "Soup")]
        ),
        encoding="utf-8",
    )
    food = {
        "label_values": [
            {"label": "Name", "value": "Food"},
            {"dict": [{"dict": _post("AAAAA1", "")["label_values"]}]},
        ]
    }
    sport = {
        "label_values": [
            {"label": "Name", "value": "Sports"},
            {"dict": [{"dict": _post("BBBBB2", "")["label_values"]}]},
        ]
    }
    (folder / "saved_collections.json").write_text(json.dumps([food, sport]), encoding="utf-8")


def test_read_export_groups_posts_by_collection_and_repairs_text(tmp_path: Path):
    _export(tmp_path / "ig")

    posts = {p.url.split("/")[-2]: p for p in read_export(tmp_path / "ig")}

    assert posts["AAAAA1"].collections == ["Food"]
    assert posts["CCCCC3"].collections == [UNCOLLECTED]
    assert posts["AAAAA1"].caption.endswith("🥳")
    assert posts["AAAAA1"].owner == "chef"


def test_import_registers_a_list_with_metadata_from_the_export(tmp_path: Path):
    _export(tmp_path / "ig")

    result = CliRunner().invoke(
        app,
        [
            "--workspace",
            str(tmp_path),
            "import-instagram",
            str(tmp_path / "ig"),
            "-c",
            "Food",
            "-c",
            "(none)",
            "--name",
            "food",
        ],
        obj=fake_adapters(),
    )

    assert result.exit_code == 0, result.output
    assert "2 posts" in result.output
    store = StateStore(tmp_path / "pipeline.db")
    assert store.list_video_keys("instagram:food") == {"instagram:AAAAA1", "instagram:CCCCC3"}
    video = store.video("instagram:AAAAA1")
    assert (
        video.metadata
        and video.metadata["description"].startswith("Pasta")
        and video.metadata["channel"] == "chef"
    )
    assert store.stage_status("video", "instagram:AAAAA1", "metadata") == "done"


def test_facebook_collections_import_only_the_chosen_collection_once_per_link(tmp_path: Path):
    def save(url: str, name: str) -> dict:
        return {
            "dict": [{"label": "URL", "value": url, "href": url}, {"label": "Name", "value": name}],
            "title": "",
        }

    reel = "https://www.facebook.com/reel/2031777400770877/"
    data = [
        {
            "label_values": [
                {"label": "Title", "value": "For later"},
                {"title": "Saves", "dict": [save(reel, "Tasty"), save(reel, "")]},
            ]
        },
        {
            "label_values": [
                {"label": "Title", "value": "House"},
                {"title": "Saves", "dict": [save("https://www.facebook.com/reel/999999999/", "Tiles")]},
            ]
        },
    ]
    (tmp_path / "collections.json").write_text(json.dumps(data), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "--workspace",
            str(tmp_path),
            "import-facebook",
            str(tmp_path / "collections.json"),
            "-c",
            "For later",
            "--name",
            "later",
        ],
        obj=fake_adapters(),
    )

    assert result.exit_code == 0, result.output
    assert StateStore(tmp_path / "pipeline.db").list_video_keys("facebook:later") == {
        "facebook:2031777400770877"
    }
