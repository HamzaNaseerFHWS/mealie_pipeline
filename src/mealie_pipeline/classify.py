"""The Classifier: is a Video a recipe? Rule signals, a batched `fast` LLM call, and the user's Overrides.

`signals(meta, rules)` is pure: hints from `config/classify_rules.yaml`, never decisions on their own.
`Classifier` asks the LLM about a batch of Videos at once, retries a batch once when its answer misses
or repeats Video Keys, and escalates uncertain or low-confidence Videos once with their subtitles.
`reports/classification.csv` lists every Video's Video Label; its `override` column always wins.
"""

import csv
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from pydantic import BaseModel, Field, ValidationError

from mealie_pipeline.adapters.llm import LLMBackend
from mealie_pipeline.adapters.video_source import VideoSourceError
from mealie_pipeline.models import VideoMeta
from mealie_pipeline.settings import ClassifySettings
from mealie_pipeline.store import StateStore, Video

Label = Literal[
    "recipe",
    "recipe_partial",
    "restaurant_or_place",
    "ad_or_product",
    "eating_or_review",
    "not_food",
    "uncertain",
]
LABELS: tuple[str, ...] = get_args(Label)
PASSING = {"recipe", "recipe_partial"}  # only these continue to the later stages
NO_ANSWER = "the classifier gave no answer for this Video"
CSV_COLUMNS = [
    "video_key",
    "url",
    "title",
    "creator",
    "label",
    "confidence",
    "reasons",
    "signals",
    "escalated",
    "source",
    "override",
]
# `mp review classify`: the key the user presses for each Video Label.
REVIEW_KEYS = {
    "r": "recipe",
    "p": "recipe_partial",
    "o": "restaurant_or_place",
    "a": "ad_or_product",
    "e": "eating_or_review",
    "n": "not_food",
}


# -- rule signals ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassifyRules:
    pro: dict[str, list[re.Pattern[str]]]
    anti: dict[str, list[re.Pattern[str]]]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ClassifyRules":
        def compile_side(side: Mapping[str, list[str]] | None) -> dict[str, list[re.Pattern[str]]]:
            return {
                name: [re.compile(p, re.IGNORECASE) for p in patterns]
                for name, patterns in (side or {}).items()
            }

        return cls(compile_side(data.get("pro")), compile_side(data.get("anti")))

    @classmethod
    def load(cls, path: Path) -> "ClassifyRules":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
        return cls.from_mapping(data or {})


@dataclass(frozen=True)
class Signals:
    """Signal name -> the text that set it off, for and against a recipe."""

    pro: dict[str, str] = field(default_factory=dict)
    anti: dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        def side(found: dict[str, str]) -> str:
            return ", ".join(f'{name} ("{text}")' for name, text in found.items()) or "none"

        return f"pro: {side(self.pro)}; anti: {side(self.anti)}"


def signals(meta: VideoMeta, rules: ClassifyRules) -> Signals:
    """The rule signals in a Video's title and caption/description."""
    text = f"{meta.title}\n{meta.description}"

    def scan(side: dict[str, list[re.Pattern[str]]]) -> dict[str, str]:
        found = {}
        for name, patterns in side.items():
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    found[name] = match.group(0)
                    break
        return found

    return Signals(scan(rules.pro), scan(rules.anti))


# -- the LLM call ---------------------------------------------------------------------------


class Classification(BaseModel):
    video_key: str
    label: Label
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list, description="Short reasons, each one sentence.")


class ClassificationBatch(BaseModel):
    items: list[Classification] = Field(description="Exactly one item per Video Key in the request.")


@dataclass(frozen=True)
class ClassifyInput:
    video_key: str
    url: str
    meta: VideoMeta
    signals: Signals
    subtitles: str = ""


@dataclass(frozen=True)
class Verdict:
    """What the Classifier decided for one Video (also how it is stored on the Video)."""

    label: str
    confidence: float
    reasons: list[str]
    escalated: bool = False
    source: str = "llm"  # llm | override | existing (its link is already a recipe in Mealie)

    @property
    def passes(self) -> bool:
        return self.label in PASSING

    def unsure(self, threshold: float) -> bool:
        return self.label == "uncertain" or self.confidence < threshold

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "escalated": self.escalated,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Verdict":
        return cls(
            str(data["label"]),
            float(data.get("confidence", 0)),
            list(data.get("reasons") or []),
            bool(data.get("escalated")),
            str(data.get("source") or "llm"),
        )


def render_prompt(items: list[ClassifyInput], settings: ClassifySettings) -> str:
    blocks = []
    for item in items:
        meta = item.meta
        duration = f"{meta.duration_s:.0f} s" if meta.duration_s else "unknown"
        caption = meta.description.strip()[: settings.caption_chars] or "(none)"
        block = (
            f"### video_key: {item.video_key}\n"
            f"Title: {meta.title or '(none)'}\nCreator: {meta.uploader or '(unknown)'}\n"
            f"Duration: {duration}\nRule signals: {item.signals.describe()}\n"
            f"Caption/description:\n{caption}\n"
        )
        if item.subtitles:
            block += f"Subtitles (start):\n{item.subtitles[: settings.subtitle_chars]}\n"
        blocks.append(block)
    return f"Classify these {len(items)} Videos. Answer with exactly one item per video_key.\n\n" + "\n".join(
        blocks
    )


def read_answers(raw: Mapping[str, Any], keys: list[str]) -> dict[str, Classification]:
    """The usable answers: valid items for keys of this batch that appear exactly once."""
    seen: dict[str, list[Classification]] = {}
    for entry in raw.get("items") or []:
        try:
            item = Classification.model_validate(entry)
        except ValidationError:
            continue
        if item.video_key in keys:
            seen.setdefault(item.video_key, []).append(item)
    return {key: found[0] for key, found in seen.items() if len(found) == 1}


class Classifier:
    def __init__(
        self,
        llm: LLMBackend,
        settings: ClassifySettings,
        subtitles: Callable[[str], str] = lambda _url: "",
    ):
        self.llm = llm
        self.settings = settings
        self.subtitles = subtitles

    def classify(self, items: list[ClassifyInput]) -> dict[str, Verdict]:
        """One batch. Raises `UsageLimited` and `LLMError` from the backend."""
        verdicts = {key: Verdict(a.label, a.confidence, a.reasons) for key, a in self._ask(items).items()}
        for item in items:
            if item.video_key not in verdicts:
                verdicts[item.video_key] = Verdict("uncertain", 0.0, [NO_ANSWER])
        threshold = self.settings.confidence_threshold
        escalate = []
        for item in items:
            if not verdicts[item.video_key].unsure(threshold):
                continue
            try:
                text = self.subtitles(item.url).strip()
            except VideoSourceError:
                text = ""
            if text:
                escalate.append(replace(item, subtitles=text))
        if escalate:  # once, with the subtitles; a Video it gives no answer for keeps its first verdict
            for key, a in self._ask(escalate).items():
                verdicts[key] = Verdict(a.label, a.confidence, a.reasons, escalated=True)
        return verdicts

    def _ask(self, items: list[ClassifyInput]) -> dict[str, Classification]:
        """One call; once more when keys are missing or repeated. Keys still missing are left out."""
        keys = [i.video_key for i in items]
        prompt = render_prompt(items, self.settings)
        schema = ClassificationBatch.model_json_schema()
        answers = read_answers(self.llm.complete("classify", prompt, schema, "fast"), keys)
        missing = [i for i in items if i.video_key not in answers]
        if missing:
            again = read_answers(self.llm.complete("classify", prompt, schema, "fast"), keys)
            answers.update({k: a for k, a in again.items() if k not in answers})
        return answers


# -- the classification CSV -----------------------------------------------------------------


def read_overrides(path: Path) -> tuple[dict[str, str], list[str]]:
    """`video_key -> label` from the `override` column, plus warnings for unknown labels."""
    if not path.is_file():
        return {}, []
    overrides, warnings = {}, []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("video_key") or "").strip()
            label = (row.get("override") or "").strip().lower()
            if not key or not label:
                continue
            if label not in LABELS:
                warnings.append(f"{key}: unknown override {label!r} in classification.csv, ignored")
                continue
            overrides[key] = label
    return overrides, warnings


def video_meta(video: Video) -> VideoMeta:
    """The Video's metadata, filled from the early listing metadata where it is missing."""
    early = video.early or {}
    meta = VideoMeta.model_validate(video.metadata) if video.metadata else VideoMeta(title="")
    return meta.model_copy(
        update={
            "title": meta.title or early.get("title") or "",
            "uploader": meta.uploader or early.get("channel") or "",
            "duration_s": meta.duration_s or early.get("duration_s"),
        }
    )


def write_classification_csv(store: StateStore, path: Path, rules: ClassifyRules | None = None) -> Path:
    """Every Video (Recipe Requests are no Videos to classify) with its Video Label; overrides kept."""
    overrides = _raw_overrides(path)
    rows = []
    for video in store.videos():
        if video.platform == "web":
            continue
        meta = video_meta(video)
        verdict = Verdict.from_dict(video.classification) if video.classification else None
        found = signals(meta, rules) if rules is not None else None
        rows.append(
            {
                "video_key": video.video_key,
                "url": video.canonical_url,
                "title": meta.title,
                "creator": meta.uploader,
                "label": verdict.label if verdict else "",
                "confidence": f"{verdict.confidence:.2f}" if verdict else "",
                "reasons": " | ".join(verdict.reasons) if verdict else "",
                "signals": found.describe() if found else "",
                "escalated": ("yes" if verdict.escalated else "no") if verdict else "",
                "source": verdict.source if verdict else "",
                "override": overrides.get(video.video_key, ""),
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:  # BOM so Excel reads UTF-8
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def set_override(path: Path, video_key: str, label: str) -> None:
    """Writes one Override into the CSV, keeping every other row as it is."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row.get("video_key") == video_key:
            row["override"] = label
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def review_queue(store: StateStore, path: Path, threshold: float) -> list[Video]:
    """Videos the classifier was unsure about and the user has not decided yet."""
    overrides = _raw_overrides(path)
    queue = []
    for video in store.videos():
        if video.platform == "web" or not video.classification or overrides.get(video.video_key):
            continue
        verdict = Verdict.from_dict(video.classification)
        if verdict.source == "llm" and verdict.unsure(threshold):
            queue.append(video)
    return queue


def _raw_overrides(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            row["video_key"]: (row.get("override") or "").strip()
            for row in csv.DictReader(handle)
            if row.get("video_key")
        }
