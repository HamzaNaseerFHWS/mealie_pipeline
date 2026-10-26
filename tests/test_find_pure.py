"""Query building, hit filtering, candidate scoring and the decision: hand-written table cases."""

import pytest

from mealie_pipeline.adapters.search import SearchHit
from mealie_pipeline.find import (
    SitePolicy,
    build_query,
    completeness,
    decide,
    filter_hits,
    guess_language,
    language_fit,
    name_similarity,
    page_language,
    score_candidate,
    single_recipe,
)
from mealie_pipeline.recipe_extraction import extract_recipes
from mealie_pipeline.settings import FindSettings
from tests.web_pages import page, recipe_json, text_only_page

CFG = FindSettings()
POLICY = SitePolicy.from_config(
    {
        "deny_domains": ["quora.com"],
        "listicle_title_patterns": [r"^\s*\d+\s+(best|easy)\b", r"\b(best|top)\s+\d+\b"],
    }
)


def recipe_of(html: str):
    recipe = single_recipe(extract_recipes(html, "https://blog.example/x", {}))
    assert recipe is not None
    return recipe


@pytest.mark.parametrize(
    ("name", "language", "hint", "query"),
    [
        ("Chicken Karahi", "en", None, "Chicken Karahi recipe"),
        ("Linsensuppe", "de", None, "Linsensuppe Rezept"),
        ("Anda Pyaz", "ur", None, "Anda Pyaz recipe"),
        ("Rajma Masala", "hi", "Indian vegetarian", "Rajma Masala recipe Indian vegetarian"),
        ("  Kheer ", "en", "  ", "Kheer recipe"),
        ("Tee", "xx", None, "Tee recipe"),  # unknown language falls back to the default template
    ],
)
def test_build_query(name, language, hint, query):
    assert build_query(name, language, hint, CFG) == query


@pytest.mark.parametrize(
    ("name", "language"),
    [
        ("Chicken Karahi", "en"),
        ("Linsensuppe", "de"),
        ("Zwiebelsuppe mit Brot & Käse überbacken", "de"),
        ("Kartoffelpuffer", "de"),
        ("Thai Mango Salad", "en"),
        ("Fisch in Mandelpanade mit Kräutersauce", "de"),
        ("Soy Hack", "en"),
        ("Mac'n'Cheese", "en"),
        ("Rajma Masala", "en"),
        ("मटर पनीर", "hi"),
        ("قورمہ", "ur"),
        ("Grießbrei", "de"),
    ],
)
def test_guess_language(name, language):
    assert guess_language(name) == language


def test_filter_drops_denylisted_listicles_duplicates_and_keeps_five():
    hits = [
        SearchHit("https://www.pinterest.com/pin/1", "Chicken Karahi"),
        SearchHit("https://www.youtube.com/watch?v=x", "Chicken Karahi video"),
        SearchHit("https://www.quora.com/How-to-cook-karahi", "Karahi question"),
        SearchHit("https://blog.example/25-chicken-recipes", "25 Best Chicken Recipes"),
        SearchHit("https://blog.example/top-10", "Top 10 karahi"),
        SearchHit("https://blog-a.example/karahi/", "Chicken Karahi"),
        SearchHit("http://www.blog-a.example/karahi?utm_source=x", "Chicken Karahi (same page)"),
        SearchHit("https://blog-b.example/karahi", "Karahi"),
        SearchHit("https://blog-c.example/karahi", "Karahi"),
        SearchHit("https://blog-d.example/karahi", "Karahi"),
        SearchHit("https://blog-e.example/karahi", "Karahi"),
        SearchHit("https://blog-f.example/karahi", "Karahi"),
        SearchHit("not a url", "garbage"),
    ]

    kept = filter_hits(hits, POLICY, keep=5)

    assert [h.url for h in kept] == [
        "https://blog-a.example/karahi/",
        "https://blog-b.example/karahi",
        "https://blog-c.example/karahi",
        "https://blog-d.example/karahi",
        "https://blog-e.example/karahi",
    ]


def test_filter_skips_pages_that_were_already_tried():
    hits = [SearchHit("https://blog-a.example/karahi"), SearchHit("https://blog-b.example/karahi")]

    kept = filter_hits(hits, POLICY, keep=5, skip={"blog-a.example/karahi"})

    assert [h.url for h in kept] == ["https://blog-b.example/karahi"]


def test_a_single_recipe_page_is_a_candidate_and_a_list_or_text_page_is_not():
    one = extract_recipes(page(recipe_json("Chicken Karahi")), "https://b.example/x", {})
    many = extract_recipes(page(recipe_json("Karahi"), recipe_json("Biryani")), "https://b.example/y", {})
    text = extract_recipes(text_only_page("Ingredients: chicken. Method: cook."), "https://b.example/z", {})
    thin = extract_recipes(page(recipe_json("Toast", ingredients=1)), "https://b.example/t", {})

    assert single_recipe(one) is not None
    assert single_recipe(many) is None  # a roundup of several recipes
    assert single_recipe(text) is None  # no structured recipe
    assert single_recipe(thin) is None  # fewer than 2 ingredients


@pytest.mark.parametrize(
    ("requested", "found", "at_least", "at_most"),
    [
        ("Chicken Karahi", "Chicken Karahi", 1.0, 1.0),
        ("Chicken Karahi", "Authentic Chicken Karahi Recipe", 0.9, 1.0),  # noise words are ignored
        ("Linsensuppe", "Einfache Linsensuppe Rezept", 0.9, 1.0),
        ("Chicken Karahi", "Butter Chicken", 0.2, 0.7),
        ("Chicken Karahi", "Chocolate Brownies", 0.0, 0.3),
        ("Tee", "", 0.0, 0.0),
    ],
)
def test_name_similarity_ranges(requested, found, at_least, at_most):
    assert at_least <= name_similarity(requested, found) <= at_most


def test_completeness_adds_up_by_hand():
    full = recipe_of(page(recipe_json("X", ingredients=4, steps=3)))
    bare = recipe_of(page(recipe_json("X", ingredients=2, steps=1, image=False)))

    # 4 ingredients (0.3) + 3 steps (0.3) + a time (0.15) + a yield (0.1) + an image (0.15)
    assert completeness(full) == 1.0
    # 2/4 ingredients (0.15) + 1/3 steps (0.1) + time (0.15) + yield (0.1), no image
    assert completeness(bare) == 0.5


@pytest.mark.parametrize(
    ("html", "language"),
    [
        ('<html lang="de-DE"><body></body></html>', "de"),
        ("<HTML LANG='en'><body></body></HTML>", "en"),
        ('<html><script type="application/ld+json">{"inLanguage": "fr"}</script></html>', "fr"),
        ("<html><body>no language</body></html>", None),
    ],
)
def test_page_language(html, language):
    assert page_language(html) == language


@pytest.mark.parametrize(
    ("wanted", "page_lang", "fit"),
    [("de", "de", 1.0), ("de", "en", 0.3), ("en", "en", 1.0), ("en", "de", 0.3), ("hi", "en", 1.0),
     ("ur", "ur", 1.0), ("ur", "de", 0.5), ("en", None, 0.5)],
)  # fmt: skip
def test_language_fit(wanted, page_lang, fit):
    assert language_fit(wanted, page_lang) == fit


def candidate(name, html, requested="Chicken Karahi", language="en", url="https://b.example/x"):
    return score_candidate(requested, language, url, recipe_of(html), html, CFG)


def test_an_exact_name_single_recipe_page_scores_by_the_weights_and_is_accepted():
    good = candidate("Chicken Karahi", page(recipe_json("Chicken Karahi", 6, 4), lang=None))

    # name 1.0*0.5 + structure (json-ld) 1.0*0.15 + completeness 1.0*0.2 + language unknown 0.5*0.15 = 0.925
    assert good is not None and good.score == pytest.approx(0.925)
    assert decide([good], CFG)[0] == "found"


def test_a_page_whose_recipe_name_does_not_resemble_the_request_is_no_candidate():
    assert candidate("x", page(recipe_json("Chocolate Brownies"))) is None


def test_two_near_identical_candidates_need_a_choice():
    a = candidate("x", page(recipe_json("Chicken Karahi")), url="https://a.example/k")
    b = candidate("x", page(recipe_json("Chicken Karahi")), url="https://b.example/k")
    assert a and b

    decision, top = decide([a, b], CFG)

    assert decision == "needs_choice" and [c.url for c in top] == [
        "https://a.example/k",
        "https://b.example/k",
    ]


def test_a_german_request_with_a_de_hint_prefers_the_german_page():
    german = candidate(
        "x", page(recipe_json("Linsensuppe"), lang="de"), "Linsensuppe", "de", "https://de.example/l"
    )
    english = candidate(
        "x", page(recipe_json("Linsensuppe"), lang="en"), "Linsensuppe", "de", "https://en.example/l"
    )
    assert german and english and german.score > english.score

    decision, top = decide([english, german], CFG)

    assert decision == "found" and top[0].url == "https://de.example/l"


def test_a_weak_match_is_offered_for_choice_not_accepted():
    weak = candidate("x", page(recipe_json("Karahi Gosht", 2, 1, image=False), lang=None))
    assert weak is not None and weak.score < CFG.accept_score

    assert decide([weak], CFG)[0] == "needs_choice"


def test_no_candidates_is_not_found():
    assert decide([], CFG) == ("not_found", [])


def test_top_three_only():
    cands = [
        candidate("x", page(recipe_json("Chicken Karahi", n + 2)), url=f"https://s{n}.example/k")
        for n in range(5)
    ]

    _, top = decide([c for c in cands if c], CFG)

    assert len(top) == 3
