"""The Outline (pure): which Videos hold several recipes, whether an LLM outline is sane, and each
part's own slice of the Sources (ADR 0006, `PIPELINE_SPEC.md` §6.1)."""

import re
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

from mealie_pipeline.models import Outline, OutlinePart, VideoMeta

Overlap = Literal["repair", "reject"]

MATCH_AT = 60  # token-set ratio at which a part's title means a website recipe's name
MAX_TITLE_WORDS = 8  # a numbered line longer than this is a method step, not a recipe heading
_MARKER = re.compile(
    r"^\s*(?:(\d{1,2})\s*[.)\]:]|(\d)️?⃣|#\s*(\d{1,2})\b|(?:recipe|rezept)\s*(\d{1,2})\b\s*[:.)-]?)",
    re.IGNORECASE,
)


class OutlineError(Exception):
    """The outline cannot be used (the Video then goes to review, or stays one recipe)."""


@dataclass(frozen=True)
class CaptionBlocks:
    intro: str  # text before the first block: shared by every part
    blocks: list[tuple[int, str]]  # (number, text from the heading to the next heading)


@dataclass(frozen=True)
class Slice:
    """One part's share of the Sources: `own` is only its, `shared` goes to every part as context."""

    title: str
    start_s: float | None
    end_s: float | None
    own: str
    shared: str
    web_index: int | None


def _heading_number(line: str) -> int | None:
    match = _MARKER.match(line)
    if match is None:
        return None
    number = next(int(g) for g in match.groups() if g)
    title = line[match.end() :].strip()
    if not title and not re.search(r"\d️?⃣", line):
        return None
    if len(title.split()) > MAX_TITLE_WORDS or title.endswith((".", "!", "?")) or "," in title:
        return None  # a sentence: a method step
    return number


def caption_blocks(description: str) -> CaptionBlocks:
    """The numbered recipe blocks of a caption ("1. Mint Chutney" and the lines under it).

    Only counts as a block list when two or more headings are numbered 1, 2, ... in a row and each
    block has lines under its heading (a method's "1. Wash the okra..." lines are sentences)."""
    lines = description.splitlines()
    marks = [(i, n) for i, line in enumerate(lines) if (n := _heading_number(line)) is not None]
    wanted = 1
    run: list[tuple[int, int]] = []
    for index, number in marks:
        if number == wanted:
            run.append((index, number))
            wanted += 1
    if len(run) < 2:
        return CaptionBlocks(description.strip(), [])
    ends = [i for i, _n in run[1:]] + [len(lines)]
    blocks = []
    for (start, number), end in zip(run, ends, strict=True):
        body = [ln for ln in lines[start + 1 : end] if ln.strip()]
        if end == len(lines) and body:  # the last block ends where its lines stop: not "Subscribe!"
            while body and not _ingredient_like(body[-1]):
                body.pop()
        blocks.append((number, "\n".join([lines[start], *body]).strip(), bool(body)))
    if len(blocks) < 2 or not all(has_body for _n, _t, has_body in blocks):
        return CaptionBlocks(description.strip(), [])
    intro = "\n".join(lines[: run[0][0]]).strip()
    return CaptionBlocks(intro, [(n, text) for n, text, _b in blocks])


def _ingredient_like(line: str) -> bool:
    """A short line is a list item; a long or exclamatory one is outro text."""
    return len(line.split()) <= MAX_TITLE_WORDS and not line.rstrip().endswith(("!", "?"))


def detect_signals(meta: VideoMeta, web_recipe_names: list[str]) -> list[str]:
    """Why this Video might hold several recipes; empty means one recipe and no outline call."""
    signals = []
    if len(meta.chapters) >= 2:
        signals.append(f"chapters:{len(meta.chapters)}")
    blocks = caption_blocks(meta.description).blocks
    if blocks:
        signals.append(f"caption_blocks:{len(blocks)}")
    distinct = {re.sub(r"\W+", " ", n).strip().casefold() for n in web_recipe_names if n.strip()}
    if len(distinct) >= 2:
        signals.append(f"website_recipes:{len(distinct)}")
    return signals


def validate_outline(
    outline: Outline, duration_s: float | None, overlap: Overlap = "repair"
) -> list[OutlinePart]:
    """The recipe parts of an LLM outline, or `OutlineError`.

    Components of another dish are dropped. Times must lie inside the Video; timed parts must not
    overlap (`repair` cuts the earlier part at the later one's start, `reject` fails). A missing end
    is the next part's start, or the end of the Video."""
    parts = [p for p in outline.parts if not p.is_component_of_other_part]
    if not parts:
        raise OutlineError("the outline has no recipe")
    timed = [p for p in parts if p.start_s is not None]
    for p in timed:
        assert p.start_s is not None
        if p.start_s < 0 or (p.end_s is not None and p.end_s <= p.start_s):
            raise OutlineError(f"{p.title!r} ends before it starts")
        if duration_s is not None and (p.start_s >= duration_s or (p.end_s or 0) > duration_s):
            raise OutlineError(f"{p.title!r} lies beyond the end of the video ({duration_s:g} s)")
    if len(timed) != len(parts):
        return parts  # not every part has times: nothing to check them against
    ordered = sorted(parts, key=lambda p: p.start_s or 0)
    result: list[OutlinePart] = []
    for index, p in enumerate(ordered):
        following = ordered[index + 1].start_s if index + 1 < len(ordered) else duration_s
        end = p.end_s if p.end_s is not None else following
        if end is not None and following is not None and end > following:
            if overlap == "reject":
                raise OutlineError(f"{p.title!r} and the next part overlap")
            end = following
        if end is not None and end <= (p.start_s or 0):
            raise OutlineError(f"{p.title!r} and the next part overlap")
        result.append(p.model_copy(update={"end_s": end}))
    return result


def segment(parts: list[OutlinePart], description: str, web_recipe_names: list[str]) -> list[Slice]:
    """Each part's own caption block and website recipe; the caption intro is shared.

    Without numbered blocks nothing in the caption can be assigned, so the whole description is
    shared context. A website recipe goes to at most one part: the one whose title is closest."""
    found = caption_blocks(description)
    by_number = dict(found.blocks)
    ordinal = len(found.blocks) == len(parts)
    web = _match_web(parts, web_recipe_names)
    slices = []
    for index, p in enumerate(parts):
        own = ""
        if found.blocks:
            if p.caption_block in by_number:
                own = by_number[p.caption_block]
            elif ordinal and p.caption_block is None:
                own = found.blocks[index][1]
        shared = found.intro if own else (found.intro if found.blocks else description.strip())
        slices.append(Slice(p.title, p.start_s, p.end_s, own, shared, web[index]))
    return slices


def _match_web(parts: list[OutlinePart], names: list[str]) -> list[int | None]:
    """Greedy best matches first, so each website recipe lands on one part."""
    scores = sorted(
        (
            (fuzz.token_set_ratio(p.title.casefold(), name.casefold()), i, j)
            for i, p in enumerate(parts)
            for j, name in enumerate(names)
        ),
        key=lambda item: -item[0],
    )
    result: list[int | None] = [None] * len(parts)
    taken: set[int] = set()
    for score, i, j in scores:
        if score >= MATCH_AT and result[i] is None and j not in taken:
            result[i] = j
            taken.add(j)
    return result
