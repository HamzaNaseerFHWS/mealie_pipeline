"""Dedupe (pure): near-duplicate Videos form a group, and one canonical Video per group continues.

Two Videos are near-duplicates when their Creators' handles are alike, their titles are alike
(fuzzy >= 85) and their upload dates are within 7 days. The canonical Video is the one with the
richest Source: a website link > a full ingredient list in the caption > YouTube > anything else.
The others become `also_on` of the canonical recipe. After parsing, `confirm` checks the group by
the food-level Jaccard of the two recipes. `reports/dedupe.csv` lists the groups; its `override`
column always wins (`split`: this Video goes on alone, `canonical`: this Video is the canonical one).
"""

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from rapidfuzz import fuzz

from mealie_pipeline.links import candidates as link_candidates

HANDLE_MIN = 80  # rapidfuzz ratio of two normalized Creator handles
TITLE_MIN = 85  # fuzzy title/caption similarity
DATE_WINDOW_DAYS = 7
JACCARD_MIN = 0.7

OVERRIDES = ("split", "canonical")
CSV_COLUMNS = [
    "group_id",
    "video_key",
    "url",
    "platform",
    "title",
    "creator",
    "role",
    "canonical_key",
    "reason",
    "override",
]
_QUANTITY_LINE = re.compile(
    r"^[ \t]*(?:[-*•][ \t]*)?(?:\d+(?:[.,/]\d+)?|[½¼¾⅓⅔])[ \t]*[^\W\d_]+", re.MULTILINE
)


@dataclass(frozen=True)
class Candidate:
    """What dedupe knows about one Video."""

    video_key: str
    platform: str
    url: str
    handle: str
    title: str
    upload_date: date | None
    has_website: bool
    has_ingredient_list: bool

    @property
    def richness(self) -> int:
        """Rank of its Source: website link 3, ingredient list in the caption 2, YouTube 1, others 0."""
        if self.has_website:
            return 3
        if self.has_ingredient_list:
            return 2
        return 1 if self.platform == "youtube" else 0


@dataclass(frozen=True)
class Group:
    canonical: str
    also_on: tuple[str, ...]
    reason: str  # why this canonical: override, existing, settled or richest source


def has_ingredient_list(description: str) -> bool:
    """A caption with an `ingredients` heading, or at least three lines that start with an amount."""
    if re.search(r"\bingredients?\b|\bzutaten\b", description, re.IGNORECASE):
        return True
    return len(_QUANTITY_LINE.findall(description)) >= 3


def parse_date(text: str | None) -> date | None:
    """yt-dlp's `YYYYMMDD` (or an ISO date) -> date; None when missing or unreadable."""
    if not text:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10] if "-" in text else text[:8], fmt).date()
        except ValueError:
            continue
    return None


def candidate(
    video_key: str,
    platform: str,
    url: str,
    *,
    handle: str,
    title: str,
    description: str,
    upload_date: str | None,
) -> Candidate:
    return Candidate(
        video_key=video_key,
        platform=platform,
        url=url,
        handle=handle,
        title=title or description.strip().split("\n", 1)[0],
        upload_date=parse_date(upload_date),
        has_website=bool(link_candidates(description)),
        has_ingredient_list=has_ingredient_list(description),
    )


def similar(a: Candidate, b: Candidate) -> bool:
    """Near-duplicates: alike Creator handles, alike titles and upload dates within a week.

    A missing handle or date never matches by itself: no handle means no match, no date is not held
    against the pair (Facebook often has none)."""
    if not a.handle or not b.handle or fuzz.ratio(a.handle, b.handle) < HANDLE_MIN:
        return False
    if not a.title.strip() or not b.title.strip():
        return False
    if fuzz.token_sort_ratio(a.title.casefold(), b.title.casefold()) < TITLE_MIN:
        return False
    if a.upload_date and b.upload_date:
        return abs((a.upload_date - b.upload_date).days) <= DATE_WINDOW_DAYS
    return True


def find_groups(cands: list[Candidate]) -> list[list[Candidate]]:
    """Connected sets of near-duplicates (two or more Videos), each in input order."""
    parent = list(range(len(cands)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, first in enumerate(cands):
        for j in range(i + 1, len(cands)):
            if similar(first, cands[j]):
                parent[root(j)] = root(i)
    members: dict[int, list[Candidate]] = {}
    for i, cand in enumerate(cands):
        members.setdefault(root(i), []).append(cand)
    return [group for group in members.values() if len(group) > 1]


def plan_groups(
    cands: list[Candidate],
    overrides: dict[str, str],
    *,
    existing: frozenset[str] = frozenset(),
    settled: frozenset[str] = frozenset(),
) -> list[Group]:
    """Groups and their canonical Video.

    A Video with the `split` override leaves its group. The canonical is chosen in this order: the
    `canonical` override, a Video whose link is already in Mealie (`existing`), a Video that already
    went on (`settled`), then the richest Source (ties: the lowest Video Key)."""
    free = [c for c in cands if overrides.get(c.video_key) != "split"]
    groups = []
    for members in find_groups(free):
        by_key = {c.video_key: c for c in members}
        picks = (
            ("override", [c for c in members if overrides.get(c.video_key) == "canonical"]),
            ("existing", [c for c in members if c.video_key in existing]),
            ("settled", [c for c in members if c.video_key in settled]),
            ("richest source", members),
        )
        reason, pool = next((pick for pick in picks if pick[1]), picks[-1])
        chosen = min(pool, key=lambda c: (-c.richness, c.video_key))
        others = tuple(k for k in by_key if k != chosen.video_key)
        groups.append(Group(chosen.video_key, others, reason))
    return groups


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def foods_of(food_names: list[str]) -> set[str]:
    return {name.strip().casefold() for name in food_names if name and name.strip()}


def confirmed(a: set[str], b: set[str]) -> bool:
    """After parsing: are two recipes of one group really the same dish?"""
    return jaccard(a, b) >= JACCARD_MIN


# -- the dedupe CSV -------------------------------------------------------------------------


def read_overrides(path: Path) -> tuple[dict[str, str], list[str]]:
    """`video_key -> override` from the `override` column, plus warnings for unknown values."""
    if not path.is_file():
        return {}, []
    overrides, warnings = {}, []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("video_key") or "").strip()
            value = (row.get("override") or "").strip().lower()
            if not key or not value:
                continue
            if value not in OVERRIDES:
                warnings.append(f"{key}: unknown override {value!r} in dedupe.csv, ignored")
                continue
            overrides[key] = value
    return overrides, warnings


def write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:  # BOM so Excel reads UTF-8
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path
