"""Link Discovery (pure): recipe-page candidates from a Video's text."""

import re
from urllib.parse import urlparse

from rapidfuzz import fuzz

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


def candidates(text: str) -> list[str]:
    """Links that could be a recipe page: short links are kept (they are expanded and re-checked)."""
    return [u for u in extract_urls(text) if is_short_link(u) or not is_denied(u)]


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
