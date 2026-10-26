"""Link Discovery: table tests (pure)."""

import pytest

from mealie_pipeline.links import candidates, choose_link, extract_urls, is_denied, is_short_link, rank_links


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Full recipe: https://foodlab.example/bhindi-aloo/", ["https://foodlab.example/bhindi-aloo/"]),
        ("see (https://foodlab.example/a).", ["https://foodlab.example/a"]),  # closing bracket and dot
        ("Recipe here: https://foodlab.example/a, and more!", ["https://foodlab.example/a"]),
        ("Blog: www.foodlab.com/bhindi-aloo", ["https://www.foodlab.com/bhindi-aloo"]),  # bare domain
        ("Blog: foodlab.com/bhindi-aloo!", ["https://foodlab.com/bhindi-aloo"]),
        (
            "https://a.example/x https://a.example/x https://b.example/y",
            ["https://a.example/x", "https://b.example/y"],
        ),
        ("mail me at chef@foodlab.com or e.g. this", []),  # an email address and "e.g." are not links
        ("Total time 2.5 hours, 1.5 tsp salt", []),  # numbers with dots are not domains
        ("", []),
    ],
)
def test_extract_urls(text, expected):
    assert extract_urls(text) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/chef",
        "https://amzn.to/3abc",
        "https://www.amazon.com/dp/B000",
        "https://shop.myshopify.com/products/pan",
        "https://linktr.ee/chef",
        "https://youtu.be/abc",
        "https://liketk.it/xyz",
    ],
)
def test_affiliate_shop_and_social_domains_are_denied(url):
    assert is_denied(url)
    assert candidates(f"Buy it: {url}") == []


def test_a_recipe_blog_is_not_denied_and_short_links_are_kept_for_expansion():
    text = "Pan: https://amzn.to/3abc  Recipe: https://bit.ly/3xyz  Blog: https://foodlab.example/lentil-soup"

    assert candidates(text) == ["https://amzn.to/3abc"][:0] + [
        "https://bit.ly/3xyz",
        "https://foodlab.example/lentil-soup",
    ]
    assert is_short_link("https://bit.ly/3xyz") and is_short_link("https://geni.us/abc")
    assert not is_short_link("https://foodlab.example/lentil-soup")


@pytest.mark.parametrize(
    ("urls", "title", "best"),
    [
        (
            ["https://blog.example/privacy-policy", "https://blog.example/crispy-okra-stir-fry"],
            "Crispy Okra Stir Fry | Bhindi",
            "https://blog.example/crispy-okra-stir-fry",
        ),
        (  # the first link wins a tie
            ["https://blog.example/aaa", "https://blog.example/bbb"],
            "Something else entirely",
            "https://blog.example/aaa",
        ),
        (  # "recipe" in the URL is a nudge
            ["https://blog.example/about-me", "https://blog.example/recipes/lentil-soup"],
            "Lentil soup",
            "https://blog.example/recipes/lentil-soup",
        ),
        (  # a home page is the last resort
            ["https://blog.example/", "https://blog.example/some-post"],
            "Unrelated",
            "https://blog.example/some-post",
        ),
    ],
)
def test_choose_link_matches_the_slug_to_the_title(urls, title, best):
    assert choose_link(urls, title) == best


def test_anchor_text_can_decide():
    urls = ["https://blog.example/p/101", "https://blog.example/p/202"]
    anchors = {urls[1]: "Easy lentil soup recipe"}

    assert choose_link(urls, "Easy Lentil Soup", anchors) == urls[1]
    assert rank_links(urls, "Easy Lentil Soup", anchors)[0] == urls[1]


def test_no_links_no_choice():
    assert choose_link([], "anything") is None
