"""Link Discovery: table tests (pure)."""

from pathlib import Path

import pytest

from mealie_pipeline.links import (
    BioLink,
    bio_links,
    candidates,
    choose_link,
    extract_urls,
    is_denied,
    is_link_in_bio,
    is_short_link,
    rank_links,
    title_match,
    video_title,
    website_of,
)


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


# -- link-in-bio pages (ticket 17) ------------------------------------------------------------

BIO = Path(__file__).parent / "fixtures" / "web" / "bio"


def bio_page(name: str) -> str:
    return (BIO / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://linktr.ee/yourfoodlab", True),
        ("https://www.lnk.bio/spicekitchen", True),
        ("https://beacons.ai/omas.kueche", True),
        ("https://bio.link/chef", True),
        ("https://yourfoodlab.example/linktr.ee", False),
        ("https://www.instagram.com/yourfoodlab", False),
    ],
)
def test_is_link_in_bio(url, expected):
    assert is_link_in_bio(url) is expected


def test_the_link_in_bio_host_list_is_configurable():
    assert not is_link_in_bio("https://linktr.ee/yourfoodlab", hosts=["lnk.bio"])
    assert is_link_in_bio("https://mylinks.example/chef", hosts=["mylinks.example"])


@pytest.mark.parametrize(
    ("fixture", "page_url", "expected"),
    [
        (
            "linktree.html",
            "https://linktr.ee/yourfoodlab",
            [
                BioLink("https://yourfoodlab.example/", "My blog: all recipes"),
                BioLink("https://yourfoodlab.example/chatpata-bhindi-aloo/", "Chatpata Bhindi Aloo"),
                BioLink("https://yourfoodlab.example/murgh-makhani/", "Butter Chicken (Murgh Makhani)"),
                BioLink("https://bit.ly/foodlab-dal", "Tadka Dal"),  # a short link is kept for expansion
            ],  # the pan (amzn.to), the socials and Linktree's own links are gone
        ),
        (
            "lnk_bio.html",
            "https://lnk.bio/spicekitchen",
            [
                BioLink("https://spicekitchen.example/recipes/palak-paneer", "Palak Paneer"),
                BioLink(
                    "https://spicekitchen.example/recipes/chicken-biryani", "Chicken Biryani (Dum style)"
                ),
            ],
        ),
        (
            "beacons.html",
            "https://beacons.ai/omas.kueche",
            [
                # no visible text: the title attribute names the link
                BioLink("https://omaskueche.example/rezepte/kaesespaetzle/", "Käsespätzle wie bei Oma"),
                BioLink("https://omaskueche.example/rezepte/apfelstrudel/", "Apfelstrudel vom Blech"),
            ],  # the second Apfelstrudel button is the same link
        ),
    ],
)
def test_bio_links(fixture, page_url, expected):
    assert bio_links(bio_page(fixture), page_url) == expected


def test_relative_links_on_a_bio_page_are_its_own_and_dropped():
    html = (
        '<a href="/s/privacy">Privacy</a>'
        '<a href="https://chef.example/dal/">Dal</a>'
        '<a href="mailto:x@y.z">Mail</a>'
    )
    assert bio_links(html, "https://linktr.ee/chef") == [BioLink("https://chef.example/dal/", "Dal")]


@pytest.mark.parametrize(
    ("title", "text", "at_least", "below"),
    [
        ("Chatpata Bhindi Aloo | Crispy Okra Stir Fry", "Chatpata Bhindi Aloo", 100, None),  # one segment
        ("Butter chicken recipe in bio", "Butter Chicken (Murgh Makhani)", 85, None),
        ("BEST Butter Chicken Recipe", "butter-chicken", 100, None),  # filler words do not count
        ("Käsespätzle wie bei Oma", "Käsespätzle wie bei Oma", 100, None),
        ("Chatpata Bhindi Aloo", "Aloo", None, 85),  # one shared word is not a match
        ("Chatpata Bhindi Aloo", "Palak Paneer", None, 50),
        ("Butter Chicken", "", None, 1),
    ],
)
def test_title_match(title, text, at_least, below):
    score = title_match(title, text)
    if at_least is not None:
        assert score >= at_least
    if below is not None:
        assert score < below


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        (
            "Chatpata Bhindi Aloo | Crispy Okra",
            "Full recipe on my blog",
            "Chatpata Bhindi Aloo | Crispy Okra",
        ),
        # Instagram reels have no real title: the caption's first line is used, without tags and links
        (
            "Video by yourfoodlab",
            "\nButter chicken 🍗 recipe in bio! #butterchicken @friend\nMore text",
            "Butter chicken 🍗 recipe in bio!",
        ),
        ("", "Palak paneer https://bit.ly/x", "Palak paneer"),
        ("Reel by spicekitchen", "", "Reel by spicekitchen"),
    ],
)
def test_video_title(title, description, expected):
    assert video_title(title, description) == expected


@pytest.mark.parametrize(
    ("url", "site"),
    [
        ("https://www.yourfoodlab.example/murgh-makhani/?utm=x", "https://www.yourfoodlab.example"),
        ("http://chef.example", "http://chef.example"),
    ],
)
def test_website_of(url, site):
    assert website_of(url) == site
