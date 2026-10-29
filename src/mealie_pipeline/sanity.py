"""Sanity Checks (pure): an ingredient line whose amount, unit or food cannot be right is `suspicious`.

Three kinds (PIPELINE_SPEC §7): a quantity out of range for its unit (any food, or a seasoning such
as "5 kg salt"), a unit used as the food ("1 cup" with no food), and a liquid counted in pieces.
The limits live in `ParseSettings`. The findings feed soft check S5; they never block a line.
"""

from mealie_pipeline.matching import singular_phrase
from mealie_pipeline.settings import ParseSettings


def _is(food: str, names: list[str]) -> bool:
    """`food` is one of `names`, or ends in one: "coconut milk" is milk, "milk powder" is not."""
    padded = f" {food}"
    return any(padded.endswith(f" {singular_phrase(name)}") for name in names)


def check_line(
    quantity: float | None, unit: str, food: str, cfg: ParseSettings, unit_words: set[str]
) -> list[str]:
    """`unit` is the English unit name ("" for none); `unit_words` every unit spelling, lower-case."""
    findings = []
    amount = quantity or 0
    name = singular_phrase(food)
    limit = cfg.max_quantity.get(unit)
    if limit is not None and amount > limit:
        findings.append(f"{amount:g} {unit} is more than {limit:g}")
    seasoning_limit = cfg.seasoning_max.get(unit)
    if seasoning_limit is not None and amount > seasoning_limit and _is(name, cfg.seasonings):
        findings.append(f"{amount:g} {unit} of {food} is implausibly much")
    # Only with no other unit: "1 tsp cloves" is the spice, "2 cloves" has lost its food.
    if not unit and {food.strip().lower(), name} & unit_words:
        findings.append(f'"{food}" is a unit, not a food')
    if amount > 0 and unit in cfg.count_units and _is(name, cfg.liquids):
        counted = f"counted in {unit}" if unit else "counted without a unit"
        findings.append(f"a liquid ({food}) {counted}")
    return findings
