"""Engine A of the Ingredient Parser: `ingredient-parser-nlp`, behind a port so tests need no model."""

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EngineParse:
    quantity: float | None
    quantity_max: float | None
    unit: str
    food: str
    note: str
    confidence: float


_WORD_QUANTITIES = {"half": 0.5, "quarter": 0.25, "third": 1 / 3, "dozen": 12.0}
_RANGE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)$")


def read_quantity(value: object) -> tuple[float | None, float | None]:
    """An amount from the parser as (quantity, quantity_max); (None, None) when it is not a number.

    The parser hands back text for amounts it cannot make a number of: "half", "few", "1.5-2", "".
    """
    if value is None or value == "":
        return None, None
    if isinstance(value, str):
        text = value.strip().lower().replace(",", ".")
        if text in _WORD_QUANTITIES:
            return _WORD_QUANTITIES[text], _WORD_QUANTITIES[text]
        if found := _RANGE.match(text):
            low, high = float(found.group(1).replace(",", ".")), float(found.group(2).replace(",", "."))
            return min(low, high), max(low, high)
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None, None
    return number, number


class IngredientEngine(Protocol):
    def parse(self, line: str) -> EngineParse: ...


class NlpIngredientEngine:
    """Wraps `ingredient_parser.parse_ingredient` (a CRF model; needs one NLTK tagger download)."""

    def __init__(self) -> None:
        self._ready = False

    def _ensure_ready(self) -> None:
        if self._ready:
            return
        import nltk

        try:
            nltk.data.find("taggers/averaged_perceptron_tagger_eng")
        except LookupError:
            nltk.download("averaged_perceptron_tagger_eng", quiet=True)
        self._ready = True

    def parse(self, line: str) -> EngineParse:
        self._ensure_ready()
        from ingredient_parser import parse_ingredient
        from ingredient_parser.dataclasses import IngredientAmount

        parsed = parse_ingredient(line, string_units=True)
        amounts = [a for a in parsed.amount if isinstance(a, IngredientAmount)]
        amount = amounts[0] if amounts else None
        quantity, quantity_max = read_quantity(amount.quantity) if amount else (None, None)
        quantity_max = (
            read_quantity(amount.quantity_max)[1] if amount and quantity is not None else quantity_max
        )
        names = parsed.name or []
        food = " ".join(n.text for n in names)
        notes = [t.text for t in (parsed.size, parsed.preparation, parsed.comment) if t is not None]
        if amount and quantity is None and isinstance(amount.quantity, str) and amount.quantity.strip():
            notes.insert(0, amount.quantity.strip())  # "few", "a pinch": keep the words, there is no number
        confidences = [n.confidence for n in names] + ([amount.confidence] if amount else [])
        return EngineParse(
            quantity=quantity,
            quantity_max=quantity_max,
            unit=str(amount.unit) if amount and amount.unit else "",
            food=food,
            note=", ".join(notes),
            confidence=min(confidences) if confidences else 0.0,
        )


class FakeIngredientEngine:
    """Scripted parses by exact line; unknown lines come back as the whole line being the food."""

    def __init__(self, parses: dict[str, EngineParse] | None = None):
        self.parses = parses or {}

    def parse(self, line: str) -> EngineParse:
        return self.parses.get(line, EngineParse(None, None, "", line, "", 0.5))
