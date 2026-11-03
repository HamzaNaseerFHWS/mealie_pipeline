"""Upload name clashes (ticket 37), pure.

Mealie keys a recipe by the slug of its name. A second recipe with a taken name is created as
"Name (1)", and a PATCH that sends the plain "Name" then fails with `400 Recipe already exists`.
So before an upload, the pipeline looks for an existing recipe with the same slug and decides:

- **same recipe**: the existing recipe's `orgURL` is one of this item's own links (the Video or the
  recipe page it links). Skip it; it is `already_in_mealie`.
- **different recipe**: upload under a distinguishing name, "Name (Channel)", falling back to the
  page's domain, then the platform, and a number when that is taken too.

An existing recipe is never overwritten.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from mealie_pipeline.existing_links import link_key


def slug_of(name: str) -> str:
    """Mealie's slug for a name, close enough to compare names: lower-case ASCII words joined by '-'.
    A name in a script with no ASCII form keeps its letters, so it still compares."""
    text = unicodedata.normalize("NFKD", name)
    ascii_text = text.encode("ascii", "ignore").decode("ascii")
    base = ascii_text if re.search(r"[A-Za-z0-9]", ascii_text) else unicodedata.normalize("NFC", name)
    return re.sub(r"[^\w]+", "-", base.casefold()).strip("-_")


@dataclass(frozen=True)
class Clash:
    slug: str
    name: str
    org_url: str


def find_clash(name: str, summaries: Iterable[dict[str, Any]], own_slugs: set[str]) -> Clash | None:
    """The existing recipe (not one of `own_slugs`) whose name takes this name's slug, if any."""
    wanted = slug_of(name)
    if not wanted:
        return None
    for summary in summaries:
        slug = str(summary.get("slug") or "")
        if not slug or slug in own_slugs:
            continue
        if slug == wanted or slug_of(str(summary.get("name") or "")) == wanted:
            return Clash(slug, str(summary.get("name") or ""), str(summary.get("orgURL") or ""))
    return None


def same_source(existing_org_url: str, own_urls: Iterable[str | None]) -> bool:
    """Is the existing recipe's link one of this item's own links (Video, or the page it links)?"""
    theirs = link_key(existing_org_url)
    if theirs is None:
        return False
    return any(theirs == link_key(u) for u in own_urls if u)


def domain_of(url: str | None) -> str:
    host = urlsplit(url or "").hostname or ""
    return host.removeprefix("www.")


def distinct_name(name: str, qualifiers: Iterable[str], taken_slugs: set[str]) -> str:
    """ "Name (Qualifier)" with the first usable qualifier whose slug is free; then "Name (Q) 2", ..."""
    usable = [q.strip().lstrip("@") for q in qualifiers if q and q.strip().lstrip("@")]
    usable = usable or ["2"]
    for qualifier in usable:
        candidate = f"{name} ({qualifier})"
        if slug_of(candidate) not in taken_slugs:
            return candidate
    first = f"{name} ({usable[0]})"
    n = 2
    while slug_of(f"{first} {n}") in taken_slugs:
        n += 1
    return f"{first} {n}"
