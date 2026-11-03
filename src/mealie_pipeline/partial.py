"""Partial recipes and link-only stubs (ticket 39, ADR 0007), pure.

- A **partial recipe** has ingredients and no steps: an Instagram caption that only lists what goes in.
- A **link-only stub** is a Video `classify` kept but whose text holds no recipe at all (hashtags,
  emoji, "full recipe in bio"). It goes to Mealie as name, thumbnail, link and tags.

`has_usable_text` decides between the two before any extraction call is spent.
"""

import re
import unicodedata
from typing import Any, Literal

RecipeKind = Literal["full", "partial", "stub"]
PARTIAL_TAG = "partial-recipe"
LINK_ONLY_TAG = "link-only"
KIND_TAGS = {"partial": PARTIAL_TAG, "stub": LINK_ONLY_TAG}
MAX_NAME = 80

_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_HASHTAG = re.compile(r"(?<!\w)#[\w-]+", re.UNICODE)
_MENTION = re.compile(r"(?<!\w)@[\w.]+", re.UNICODE)
_NUMBER = r"(?:\d+(?:[.,/]\d+)?|[½⅓⅔¼¾⅛])"
_UNITS = (
    r"g|gm|gms|gr|gram|grams|kg|kgs|kilo|mg|ml|l|ltr|litre|liter|liters|litres|tbsp|tbs|tbl|tablespoons?|"
    r"tsp|teaspoons?|cups?|oz|ounces?|lbs?|pounds?|pinch|cloves?|slices?|pieces?|pcs|bunch|cans?|"
    r"sprigs?|handful|packets?|el|tl|prise|stück|zehen?|bund|dose|becher|pao|chamach|chamche"
)
_QUANTITY_LINE = re.compile(
    rf"^\s*(?:[-*•▪◦·✓✔✅➡️>]\s*)?{_NUMBER}\s*(?:-\s*{_NUMBER}\s*)?(?:{_UNITS})?\b", re.I
)
_UNIT_ANYWHERE = re.compile(rf"\b{_NUMBER}\s*(?:{_UNITS})\b", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•▪◦·✓✔✅➡️]|\d+[.)])\s*\S")
_HEADING = re.compile(
    r"^\s*(?:[^\w\s]\s*)*(ingredients?|zutaten|ajza|ajzaa|ingredienten|ingrédients|what you need)\b",
    re.IGNORECASE,
)
_COOKING = re.compile(
    r"\b(add|bake|boil|chop|cook|fry|grill|heat|mix|simmer|stir|roast|marinate|knead|whisk|blend|"
    r"saute|sauté|season|serve|pour|combine|preheat|braten|kochen|backen|anbraten|hinzufügen)\b",
    re.IGNORECASE,
)
_SUFFIXES = re.compile(r"\s*[|•–—-]\s*[^|•–—-]*$")  # "Okra Fry | Your Food Lab" -> "Okra Fry"


def clean_text(text: str) -> str:
    """The text without links, hashtags, @mentions and emoji."""
    text = _URL.sub(" ", text or "")
    text = _HASHTAG.sub(" ", text)
    text = _MENTION.sub(" ", text)
    return "".join(ch for ch in text if not _is_emoji(ch))


def _is_emoji(ch: str) -> bool:
    if ch in "½⅓⅔¼¾⅛":
        return False
    category = unicodedata.category(ch)
    return category in ("So", "Sk", "Cs", "Co") or ord(ch) in (0x200D, 0xFE0F)


def ingredient_lines(text: str) -> int:
    """How many lines look like an ingredient: an amount at the start ("2 tbsp oil", "- 250 g okra"),
    an amount with a unit anywhere, or a bullet under an "Ingredients" heading."""
    count = 0
    under_heading = False
    for raw in clean_text(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        if _HEADING.match(line):
            under_heading = True
            rest = _HEADING.sub("", line).strip(" :-")
            count += sum(1 for piece in re.split(r"[,;]", rest) if piece.strip())  # "Ingredients: a, b"
            continue
        if (
            _QUANTITY_LINE.match(line)
            or _UNIT_ANYWHERE.search(line)
            or (under_heading and (_BULLET.match(line) or len(line.split()) <= 5))
        ):
            count += 1
    return count


def has_usable_text(texts: list[str]) -> bool:
    """Is there anything to extract a recipe from? At least two ingredient lines, or a method: a few
    sentences with cooking verbs. Hashtags, emoji, links and promo text are not enough."""
    joined = "\n".join(t for t in texts if t)
    if ingredient_lines(joined) >= 2:
        return True
    cleaned = clean_text(joined)
    return len(_COOKING.findall(cleaned)) >= 3 and len(cleaned.split()) >= 25


def stub_name(title: str, caption: str) -> str | None:
    """The stub's name: the title, else the first caption line with words in it, cleaned up. None when
    there is nothing to call it (then the stub is held for review)."""
    for candidate in (title, *(caption or "").splitlines()):
        name = _clean_name(candidate or "")
        if name:
            return name
    return None


def _clean_name(text: str) -> str:
    name = " ".join(clean_text(text).split())
    name = re.sub(r"\b(shorts|reels?|viral|trending|fyp)\b", " ", name, flags=re.IGNORECASE)
    name = " ".join(name.split()).strip(" .,:;!?-|•–—")
    if "|" in name or " - " in name or " – " in name:
        trimmed = _SUFFIXES.sub("", name).strip(" .,:;!?-|•–—")
        name = trimmed or name
    if not re.search(r"\w{2,}", name):
        return ""
    if len(name) > MAX_NAME:
        name = name[:MAX_NAME].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return name[:1].upper() + name[1:]


def recipe_kind(extracted: dict[str, Any] | None) -> RecipeKind:
    """What a Recipe Part's extraction is: a stub has neither ingredients nor steps, a partial
    recipe ingredients only."""
    if not extracted:
        return "full"
    if extracted.get("ingredients") and not extracted.get("instructions"):
        return "partial"
    if not extracted.get("ingredients") and not extracted.get("instructions"):
        return "stub"
    return "full"
