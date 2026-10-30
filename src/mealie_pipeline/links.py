"""Link Discovery (pure): recipe-page candidates from a Video's text, and the links on link-in-bio pages."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from rapidfuzz import fuzz
from selectolax.lexbor import LexborHTMLParser as HTMLParser

SHORT_LINK_DOMAINS = {
    "bit.ly", "tinyurl.com", "geni.us", "ow.ly", "buff.ly", "is.gd", "rb.gy", "cutt.ly", "lnkd.in",
    "t.ly", "shorturl.at", "tiny.cc",
}  # fmt: skip

# Social, shopping, affiliate and link-in-bio hosts that never hold the recipe itself.
DENYLIST = {
    "instagram.com", "facebook.com", "fb.com", "fb.me", "fb.watch", "twitter.com", "x.com", "tiktok.com",
    "youtube.com", "youtu.be", "pinterest.com", "pin.it", "threads.net", "snapchat.com", "reddit.com",
    "amazon.com", "amazon.de", "amazon.co.uk", "amazon.in", "amzn.to", "amzn.com", "a.co", "ebay.com",
    "etsy.com", "walmart.com", "target.com", "shopify.com", "myshopify.com", "liketk.it", "ltk.app",
    "shopltk.com", "rstyle.me", "shopstyle.com", "shareasale.com", "awin1.com", "kit.co", "skimlinks.com",
    "patreon.com", "paypal.com", "paypal.me", "buymeacoffee.com", "ko-fi.com", "discord.gg",
    "discord.com", "spotify.com", "apple.com", "t.me", "wa.me", "whatsapp.com", "linktr.ee", "lnk.bio",
    "beacons.ai", "bio.link", "carrd.co", "google.com", "goo.gl", "forms.gle",
}  # fmt: skip

# Link-in-bio pages: they list the creator's links, so they are opened (in the Browser) and read.
LINK_IN_BIO_HOSTS = ("linktr.ee", "lnk.bio", "beacons.ai", "bio.link")

_TLDS = (
    "com|org|net|io|co|de|uk|in|pk|info|blog|recipes|food|kitchen|eu|fr|es|it|ca|au|tv|me|app|page|"
    "site|online|cooking|ch|at|nl|us"
)
_URL = re.compile(
    rf"(?:https?://[^\s<>\"']+)"
    rf"|(?<![@\w./-])(?:www\.)?(?:[a-z0-9-]+\.)+(?:{_TLDS})(?:/[^\s<>\"']*)?(?![\w@])",
    re.IGNORECASE,
)
_TRAILING = ".,;:!?)]}>\"'*»”’"


def host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _on_list(host: str, domains: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def is_denied(url: str) -> bool:
    return _on_list(host_of(url), DENYLIST)


def is_short_link(url: str) -> bool:
    return _on_list(host_of(url), SHORT_LINK_DOMAINS)


def extract_urls(text: str) -> list[str]:
    """URLs in order of appearance, deduplicated; bare domains get `https://`; trailing punctuation goes."""
    found: list[str] = []
    for match in _URL.finditer(text or ""):
        url = match.group(0).rstrip(_TRAILING)
        if not url:
            continue
        if not url.lower().startswith("http"):
            url = "https://" + url
        if urlparse(url).hostname and url not in found:
            found.append(url)
    return found


def is_link_in_bio(url: str, hosts: Iterable[str] = LINK_IN_BIO_HOSTS) -> bool:
    return _on_list(host_of(url), {h.lower() for h in hosts})


def candidates(text: str, keep: Iterable[str] = ()) -> list[str]:
    """Links that could be a recipe page: short links are kept (they are expanded and re-checked),
    and so are links to the `keep` hosts (the link-in-bio pages that are opened)."""
    keep = set(keep)
    return [
        u for u in extract_urls(text) if is_short_link(u) or _on_list(host_of(u), keep) or not is_denied(u)
    ]


def website_of(url: str) -> str:
    """The Recipe Website a page belongs to: its scheme and host, e.g. `https://chef.example`."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def is_home_page(url: str) -> bool:
    return urlparse(url).path.strip("/") == ""


@dataclass(frozen=True)
class BioLink:
    url: str
    text: str


def bio_links(html: str, page_url: str) -> list[BioLink]:
    """The outgoing links of a rendered link-in-bio page, in order, each with its button text.

    The page host's own links (sign-up, privacy, report) and denylisted ones (socials, shops) go;
    short links stay so they can be expanded. A link listed twice keeps its first text."""
    own = host_of(page_url)
    found: dict[str, str] = {}
    for anchor in HTMLParser(html).css("a[href]"):
        url = urljoin(page_url, (anchor.attributes.get("href") or "").strip())
        if not url.startswith(("http://", "https://")) or host_of(url) in ("", own):
            continue
        if url in found or (is_denied(url) and not is_short_link(url)):
            continue
        text = " ".join(anchor.text(separator=" ").split())
        found[url] = text or (anchor.attributes.get("title") or anchor.attributes.get("aria-label") or "")
    return [BioLink(url, text) for url, text in found.items()]


# Words that say nothing about which dish a title or link is about.
_FILLER = {
    "recipe", "recipes", "rezept", "rezepte", "easy", "best", "quick", "simple", "homemade", "the", "a",
    "an", "and", "with", "how", "to", "make", "making", "my", "full", "style", "in", "bio", "link", "on",
    "of", "shorts", "reel", "video", "blog", "website",
}  # fmt: skip
_SEGMENT = re.compile(r"\s+[|–—:]\s+|\s+-\s+|\|")
_GENERIC_TITLE = re.compile(r"^(video|reel|post|photo) by \S+$", re.IGNORECASE)
_TAG_OR_MENTION = re.compile(r"[#@][^\s#@]+")


def title_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[^\W_]+", text.casefold()) if w not in _FILLER]


def title_match(title: str, text: str) -> float:
    """0-100: how surely `text` (a link's text, a page title or a slug) names the dish of the Video
    title. Each `|`/`-`/`:` segment of the title is tried on its own; filler words do not count.
    One side may hold extra words only when they share at least two words."""
    target = title_words(text.replace("-", " "))
    if not target:
        return 0.0
    best = 0.0
    for segment in [title, *_SEGMENT.split(title)]:
        words = title_words(segment)
        if not words:
            continue
        a, b = " ".join(words), " ".join(target)
        score = fuzz.token_sort_ratio(a, b)
        if len(set(words) & set(target)) >= 2:
            score = max(score, fuzz.token_set_ratio(a, b))
        best = max(best, score)
    return best


def video_title(title: str, description: str) -> str:
    """The title to match pages against. Instagram and Facebook give "Video by <handle>" or nothing;
    then the caption's first line is used, without hashtags, mentions and links."""
    if title.strip() and not _GENERIC_TITLE.match(title.strip()):
        return title.strip()
    for line in description.splitlines():
        cleaned = _URL.sub("", _TAG_OR_MENTION.sub("", line))
        cleaned = " ".join(cleaned.split())
        if re.search(r"[^\W\d_]", cleaned):
            return cleaned
    return title.strip()


def _slug_text(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return re.sub(r"[-_/.]+", " ", path).strip()


def rank_links(urls: list[str], title: str, anchors: dict[str, str] | None = None) -> list[str]:
    """Best match first: slug (or anchor text) similarity to the Video title, a nudge for URLs that say
    "recipe", and home pages (no path) last. Equal scores keep the order of appearance."""
    anchors = anchors or {}

    def score(url: str) -> float:
        slug = _slug_text(url)
        anchor = anchors.get(url, "")
        if not slug and not anchor:
            return -50.0
        best = max(
            fuzz.token_set_ratio(title.casefold(), slug.casefold()) if slug else 0,
            fuzz.token_set_ratio(title.casefold(), anchor.casefold()) if anchor else 0,
        )
        return best + (20 if "recipe" in url.lower() else 0)

    scored = [(score(u), -i, u) for i, u in enumerate(urls)]
    return [u for _, _, u in sorted(scored, reverse=True)]


def choose_link(urls: list[str], title: str, anchors: dict[str, str] | None = None) -> str | None:
    ranked = rank_links(urls, title, anchors)
    return ranked[0] if ranked else None
