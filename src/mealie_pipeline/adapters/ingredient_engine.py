"""Engine A of the Ingredient Parser: `ingredient-parser-nlp`, behind a port so tests need no model."""

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
        names = parsed.name or []
        food = " ".join(n.text for n in names)
        notes = [t.text for t in (parsed.size, parsed.preparation, parsed.comment) if t is not None]
        confidences = [n.confidence for n in names] + ([amount.confidence] if amount else [])
        return EngineParse(
            quantity=float(amount.quantity) if amount and amount.quantity is not None else None,
            quantity_max=float(amount.quantity_max) if amount and amount.quantity_max is not None else None,
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
