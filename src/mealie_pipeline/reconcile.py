"""Reconcile (pure): the two ingredient parses of one English line become one, with a parse status.

Engine A is `ingredient-parser-nlp`, engine B the LLM parse from the extraction call (PIPELINE_SPEC §7):
- `agreed`: quantity equal, both units stand for the same unit, foods alike (>= 90): take engine A.
- `nlp_preferred`: exactly one of those fields differs and engine A is sure of it (>= 0.9).
- `conflict`: anything else; the LLM's reading is used and the line counts against the score.
- `unparsed`: neither engine found a food; the line is kept as a note.
- `nlp_only`: there is no LLM parse (an extraction from before the second engine).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

from rapidfuzz import fuzz

from mealie_pipeline.adapters.ingredient_engine import EngineParse
from mealie_pipeline.matching import singular_phrase
from mealie_pipeline.models import LlmParse, ParseStatus

NLP_CONFIDENCE = 0.9
FOOD_AGREEMENT = 90


@dataclass(frozen=True)
class Reconciled:
    status: ParseStatus
    quantity: float | None
    quantity_max: float | None
    unit: str
    food: str
    note: str
    differing: tuple[str, ...] = ()  # "quantity" / "unit" / "food", in that order


def _same_amount(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=0.02, abs_tol=0.01)  # 1/3 and 0.33 are the same amount


def _same_food(a: str, b: str, threshold: float) -> bool:
    a, b = singular_phrase(a), singular_phrase(b)
    return bool(a and b) and fuzz.ratio(a, b) >= threshold


def _from_nlp(status: ParseStatus, nlp: EngineParse, note: str, differing: tuple[str, ...]) -> Reconciled:
    return Reconciled(status, nlp.quantity, nlp.quantity_max, nlp.unit, nlp.food, note, differing)


def reconcile(
    line: str,
    nlp: EngineParse,
    llm: LlmParse | None,
    unit_key: Callable[[str], str],
    *,
    nlp_confidence: float = NLP_CONFIDENCE,
    food_agreement: float = FOOD_AGREEMENT,
) -> Reconciled:
    """`unit_key` maps a unit spelling to the unit it stands for, so "tbsps" and "tablespoon" agree."""
    llm_food = ((llm.food if llm else None) or "").strip()
    if not nlp.food.strip() and not llm_food:
        return Reconciled("unparsed", None, None, "", "", line)
    if llm is None:
        return _from_nlp("nlp_only", nlp, nlp.note, ())

    llm_max = llm.quantity_max if llm.quantity_max is not None else llm.quantity
    llm_unit, llm_note = (llm.unit or "").strip(), (llm.note or "").strip()
    same = {
        "quantity": _same_amount(nlp.quantity, llm.quantity) and _same_amount(nlp.quantity_max, llm_max),
        "unit": unit_key(nlp.unit) == unit_key(llm_unit),
        "food": _same_food(nlp.food, llm_food, food_agreement),
    }
    differing = tuple(name for name, ok in same.items() if not ok)
    if not differing:
        return _from_nlp("agreed", nlp, nlp.note or llm_note, ())
    if len(differing) == 1 and nlp.confidence_of(differing[0]) >= nlp_confidence:
        return _from_nlp("nlp_preferred", nlp, nlp.note or llm_note, differing)
    return Reconciled("conflict", llm.quantity, llm_max, llm_unit, llm_food, llm_note, differing)
