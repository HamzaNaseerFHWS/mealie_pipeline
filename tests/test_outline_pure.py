"""Outline signals, validation and segmentation at the pure-module seam (ticket 12)."""

import pytest

from mealie_pipeline.models import Chapter, Outline, OutlinePart, VideoMeta
from mealie_pipeline.outline import (
    OutlineError,
    caption_blocks,
    detect_signals,
    segment,
    validate_outline,
)

CAPTION = """Three chutneys for your table!

1. Mint Chutney
1 cup mint
2 green chillies
salt

2. Tamarind Chutney
100 g tamarind
50 g jaggery

3️⃣ Coconut Chutney
1 coconut
2 tbsp curd

Subscribe for more!"""

OKRA_STEPS = """INGREDIENTS
250 g okra (bhindi)
2 small onions

METHOD
1. Wash the okra, dry it well and cut into thick dice.
2. Heat the oil in a kadhai and cook until translucent.
3. Add the okra and cook covered on low heat until tender. Season with salt and serve.
"""


def part(title, start=None, end=None, **kw) -> OutlinePart:
    return OutlinePart(title=title, start_s=start, end_s=end, **kw)


def test_numbered_caption_blocks_become_blocks_with_a_shared_intro():
    found = caption_blocks(CAPTION)

    assert found.intro.startswith("Three chutneys")
    assert [(n, text.splitlines()[0]) for n, text in found.blocks] == [
        (1, "1. Mint Chutney"),
        (2, "2. Tamarind Chutney"),
        (3, "3️⃣ Coconut Chutney"),
    ]
    assert "50 g jaggery" in found.blocks[1][1] and "jaggery" not in found.blocks[0][1]


def test_numbered_method_steps_are_not_recipe_blocks():
    assert caption_blocks(OKRA_STEPS).blocks == []


def test_a_single_numbered_item_is_not_a_block_list():
    assert caption_blocks("1. Mint Chutney\n1 cup mint\n2 chillies\n").blocks == []


@pytest.mark.parametrize(
    ("meta", "names", "expected"),
    [
        (VideoMeta(title="t", description="plain text"), [], []),
        (
            VideoMeta(title="t", chapters=[Chapter(title="Intro", start_s=0, end_s=10)]),
            [],
            [],
        ),  # one chapter is no outline
        (
            VideoMeta(
                title="t",
                chapters=[Chapter(title="A", start_s=0, end_s=60), Chapter(title="B", start_s=60, end_s=120)],
            ),
            [],
            ["chapters:2"],
        ),
        (VideoMeta(title="t", description=CAPTION), [], ["caption_blocks:3"]),
        (VideoMeta(title="t"), ["Pasta", "Salad"], ["website_recipes:2"]),
        (VideoMeta(title="t"), ["Pasta", "pasta"], []),  # the same recipe twice is one recipe
        (VideoMeta(title="t", description=OKRA_STEPS), ["Okra"], []),
    ],
)
def test_signals(meta, names, expected):
    assert detect_signals(meta, names) == expected


def test_chapters_become_parts_and_components_are_dropped():
    outline = Outline(
        language="en",
        parts=[
            part("Biryani", 0, 300),
            part("Marinade", 30, 90, is_component_of_other_part=True),
            part("Raita", 300, 420),
        ],
    )

    parts = validate_outline(outline, duration_s=420)

    assert [p.title for p in parts] == ["Biryani", "Raita"]


def test_an_outline_with_no_parts_or_only_components_is_rejected():
    with pytest.raises(OutlineError, match="no recipe"):
        validate_outline(Outline(language="en", parts=[]), duration_s=60)
    only = Outline(language="en", parts=[part("Marinade", is_component_of_other_part=True)])
    with pytest.raises(OutlineError, match="no recipe"):
        validate_outline(only, duration_s=60)


def test_times_beyond_the_video_are_rejected():
    with pytest.raises(OutlineError, match="beyond"):
        validate_outline(
            Outline(language="en", parts=[part("A", 0, 100), part("B", 100, 900)]), duration_s=600
        )
    with pytest.raises(OutlineError, match="before"):
        validate_outline(Outline(language="en", parts=[part("A", 50, 20)]), duration_s=600)


def test_overlapping_timestamps_are_repaired_by_cutting_the_earlier_part():
    outline = Outline(language="en", parts=[part("B", 100, 300), part("A", 0, 150)])

    parts = validate_outline(outline, duration_s=300, overlap="repair")

    assert [(p.title, p.start_s, p.end_s) for p in parts] == [("A", 0, 100), ("B", 100, 300)]


def test_overlapping_timestamps_are_rejected_when_settings_say_so():
    outline = Outline(language="en", parts=[part("A", 0, 150), part("B", 100, 300)])
    with pytest.raises(OutlineError, match="overlap"):
        validate_outline(outline, duration_s=300, overlap="reject")


def test_a_part_that_overlap_repair_would_empty_is_rejected():
    outline = Outline(language="en", parts=[part("A", 0, 100), part("B", 0, 50)])
    with pytest.raises(OutlineError, match="overlap"):
        validate_outline(outline, duration_s=300, overlap="repair")


def test_missing_ends_are_filled_from_the_next_start_and_the_duration():
    outline = Outline(language="en", parts=[part("A", 0), part("B", 120)])

    parts = validate_outline(outline, duration_s=300)

    assert [(p.start_s, p.end_s) for p in parts] == [(0, 120), (120, 300)]


def test_each_part_gets_its_own_caption_block_and_the_intro_is_shared():
    outline = Outline(language="en", parts=[part("Mint"), part("Tamarind"), part("Coconut")])

    slices = segment(validate_outline(outline, None), CAPTION, [])

    assert [s.title for s in slices] == ["Mint", "Tamarind", "Coconut"]
    assert "1 cup mint" in slices[0].own and "tamarind" not in slices[0].own.lower()
    assert "50 g jaggery" in slices[1].own and "mint" not in slices[1].own.lower()
    assert all(s.shared.startswith("Three chutneys") for s in slices)
    assert all("Subscribe" not in s.shared for s in slices)


def test_a_part_names_its_caption_block_by_number():
    outline = Outline(language="en", parts=[part("Coconut", caption_block=3), part("Mint", caption_block=1)])

    slices = segment(outline.parts, CAPTION, [])

    assert "1 coconut" in slices[0].own and "1 cup mint" in slices[1].own


def test_without_blocks_the_whole_description_is_shared_context():
    outline = Outline(language="en", parts=[part("A", 0, 60), part("B", 60, 120)])

    slices = segment(validate_outline(outline, 120), "Just a caption", [])

    assert [(s.own, s.shared) for s in slices] == [("", "Just a caption")] * 2


def test_two_recipe_objects_on_a_page_are_matched_to_parts_by_name():
    outline = Outline(language="en", parts=[part("Spicy Salad"), part("Creamy Pasta")])

    slices = segment(outline.parts, "", ["Creamy Pasta Bake", "Spicy Summer Salad"])

    assert [s.web_index for s in slices] == [1, 0]


def test_a_web_recipe_is_never_given_to_two_parts_and_unmatched_parts_get_none():
    outline = Outline(language="en", parts=[part("Pasta"), part("Pasta again"), part("Soup")])

    slices = segment(outline.parts, "", ["Pasta"])

    assert [s.web_index for s in slices] == [0, None, None]
