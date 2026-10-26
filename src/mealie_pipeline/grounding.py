"""Grounding (pure): does an Evidence quote really occur in the Source it cites?

Comparison is on normalized text (Unicode NFKC, case-folded, punctuation dropped, whitespace
collapsed) and tolerant of small differences (fuzzy containment >= threshold). Letters and combining
marks of every script are kept, so a Devanagari or Nastaliq quote is matched against Devanagari or
Nastaliq text, never against a translation.
"""

import unicodedata

from rapidfuzz import fuzz

from mealie_pipeline.models import Evidence, ExtractedIngredient, ExtractedStep

_TATWEEL = "ـ"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace(_TATWEEL, "")
    kept = [
        " " if ch.isspace() or unicodedata.category(ch)[0] in "PSC" else ch  # punctuation, symbols, controls
        for ch in text
    ]
    return " ".join("".join(kept).split())


def is_grounded(quote: str, source_text: str, threshold: float = 90) -> bool:
    needle, haystack = normalize(quote), normalize(source_text)
    if not needle or not haystack:
        return False
    if needle in haystack:
        return True
    return fuzz.partial_ratio(needle, haystack) >= threshold


def evidence_grounded(evidence: list[Evidence], sources: dict[str, str], threshold: float = 90) -> bool:
    """True when at least one quote is found in the Source it cites (and every cited Source exists)."""
    return bool(evidence) and any(
        e.source in sources and is_grounded(e.quote, sources[e.source], threshold) for e in evidence
    )


def ungrounded_ingredients(
    ingredients: list[ExtractedIngredient], sources: dict[str, str], threshold: float = 90
) -> list[int]:
    return [i for i, ing in enumerate(ingredients) if not evidence_grounded(ing.evidence, sources, threshold)]


def ungrounded_steps(steps: list[ExtractedStep], sources: dict[str, str], threshold: float = 90) -> list[int]:
    return [i for i, step in enumerate(steps) if not evidence_grounded(step.evidence, sources, threshold)]
