"""Grounding: table tests for normalized fuzzy containment (pure)."""

import pytest

from mealie_pipeline.grounding import evidence_grounded, is_grounded, normalize, ungrounded_ingredients
from mealie_pipeline.models import Evidence, ExtractedIngredient, SourceKind

SOURCE = (
    "INGREDIENTS\n250 g Okra (bhindi)\n2  small   onions,\nSalt, to taste\nMethod: Heat the oil in a kadhai."
)


@pytest.mark.parametrize(
    ("quote", "grounded"),
    [
        ("250 g okra (bhindi)", True),  # exact
        ("250 G OKRA BHINDI", True),  # case and punctuation
        ("2 small\nonions", True),  # whitespace and line breaks
        ("Salt to taste", True),  # missing comma
        ("250 g okra (bhindhi)", True),  # one-letter typo stays above 90
        ("250 g okra, bhindi, trimmed", False),  # extra invented words
        ("2 cups saffron", False),  # not in the source at all
        ("heat the oil in a kadhai", True),
        ("", False),
        ("   ...  ", False),
    ],
)
def test_is_grounded(quote, grounded):
    assert is_grounded(quote, SOURCE) is grounded


def test_fullwidth_and_compatibility_characters_are_normalized():
    assert is_grounded("２５０ ｇ okra", "250 g okra")  # NFKC folds full-width digits and letters


def test_a_devanagari_quote_is_matched_in_devanagari_not_in_a_translation():
    source = "सामग्री: 2 प्याज़, 1 चम्मच हल्दी\nविधि: प्याज़ को भून लें।"

    assert is_grounded("1 चम्मच हल्दी", source)
    assert is_grounded("प्याज़ को भून लें", source)  # the danda is punctuation and is ignored
    assert not is_grounded("1 tablespoon turmeric", source)  # a translated quote is not evidence


def test_a_nastaliq_quote_is_matched_in_urdu_script():
    source = "اجزاء: دو پیاز، ایک چمچ ہلدی\nترکیب: پیاز کو بھون لیں۔"

    assert is_grounded("ایک چمچ ہلدی", source)
    assert not is_grounded("एक चम्मच हल्दी", source)  # Devanagari does not match Nastaliq


def test_normalize_keeps_combining_marks_so_devanagari_words_stay_intact():
    assert normalize("प्याज़,  हल्दी!") == "प्याज़ हल्दी"


def ingredient(quote: str, source: SourceKind = "desc"):
    return ExtractedIngredient(
        line="x", original_line="x", quantity_stated=True, evidence=[Evidence(source=source, quote=quote)]
    )


def test_only_the_cited_source_counts():
    sources = {"desc": "2 small onions", "cmt": "1 tsp cumin"}

    bad = ungrounded_ingredients(
        [
            ingredient("2 small onions"),  # found in desc
            ingredient("1 tsp cumin"),  # cited as desc but only the comment has it
            ingredient("1 tsp cumin", source="cmt"),
            ingredient("2 small onions", source="web"),  # cites a Source that does not exist
        ],
        sources,
    )

    assert bad == [1, 3]


def test_an_ingredient_without_evidence_is_ungrounded():
    no_evidence = ExtractedIngredient(line="x", original_line="x", quantity_stated=True, evidence=[])

    assert not evidence_grounded(no_evidence.evidence, {"desc": "x"})
