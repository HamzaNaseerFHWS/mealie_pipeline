"""Rule Tags, contradiction removal and tag ranking at the pure-module seam."""

from mealie_pipeline.tagging import RecipeFacts, TagRules, choose, contradictions, match_existing, rule_tags

RULES = TagRules.from_dict(
    {
        "food_groups": {
            "meat": ["chicken", "beef", "lamb"],
            "fish": ["salmon", "tuna"],
            "egg": ["egg"],
            "dairy": ["milk", "butter", "paneer"],
        },
        "drink_words": ["smoothie", "lassi", "juice"],
        "rules": [
            {"tag": "Vegetarian", "when": {"no_foods_in": ["meat", "fish"]}},
            {"tag": "Vegan", "when": {"no_foods_in": ["meat", "fish", "egg", "dairy"]}},
            {"tag": "Quick", "when": {"max_total_minutes": 30}},
            {"tag": "Drinks", "when": {"drink": True}},
            {"tag": "Deutsch", "when": {"language": ["de"]}},
        ],
        "contradictions": [
            {"tag": "Vegetarian", "foods_in": ["meat", "fish"]},
            {"tag": "Vegan", "foods_in": ["meat", "fish", "egg", "dairy"]},
        ],
    }
)


def facts(*foods: str, name="Dish", minutes=None, language="en") -> RecipeFacts:
    return RecipeFacts(name, list(foods), minutes, language)


def test_a_recipe_without_meat_or_fish_is_vegetarian_and_vegan_needs_no_egg_or_dairy():
    assert rule_tags(facts("okra", "egg", minutes=45), RULES) == ["Vegetarian"]
    assert rule_tags(facts("okra", "onion", minutes=45), RULES) == ["Vegetarian", "Vegan"]


def test_meat_or_fish_foods_block_the_vegetarian_rule():
    assert rule_tags(facts("Chicken thighs", minutes=45), RULES) == []
    assert rule_tags(facts("salmon", minutes=45), RULES) == []


def test_time_language_and_drink_rules():
    assert rule_tags(facts("chicken", minutes=30), RULES) == ["Quick"]
    assert rule_tags(facts("chicken", minutes=31), RULES) == []
    assert rule_tags(facts("chicken"), RULES) == []  # unknown time is never quick
    assert rule_tags(facts("chicken", language="de"), RULES) == ["Deutsch"]
    assert rule_tags(facts("mango", name="Mango Lassi", minutes=5), RULES) == [
        "Vegetarian",
        "Vegan",
        "Quick",
        "Drinks",
    ]


def test_contradictions_name_the_tag_and_the_food_that_contradicts_it():
    found = contradictions(["Dinner", "vegetarian ", "Vegan"], facts("chicken", "milk"), RULES)
    assert found == {"vegetarian ": "chicken", "Vegan": "chicken"}
    assert contradictions(["Vegan"], facts("egg"), RULES) == {"Vegan": "egg"}
    assert contradictions(["Vegan"], facts("okra"), RULES) == {}


def test_matching_ignores_case_whitespace_and_punctuation():
    existing = ["Quick", "Dinner", "One-Pot"]
    assert match_existing("Quick ", existing) == "Quick"
    assert match_existing("quick", existing) == "Quick"
    assert match_existing("Quick!", existing) == "Quick"
    assert match_existing("one pot", existing) == "One-Pot"
    assert match_existing("Brunch", existing) is None


def test_rule_tags_come_first_then_llm_tags_by_rank_deduped_and_capped_at_six():
    result = choose(["Quick", "Chicken"], ["Dinner", "quick", "A", "B", "C", "D", "E"], max_tags=6)
    assert result == ["Quick", "Chicken", "Dinner", "A", "B", "C"]
    assert choose([], [], max_tags=6) == []
