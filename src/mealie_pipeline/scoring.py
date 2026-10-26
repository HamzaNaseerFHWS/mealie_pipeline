"""The Quality Score and the Gate's decision (pure)."""

from dataclasses import dataclass
from typing import Literal

from mealie_pipeline.settings import VerifySettings

Outcome = Literal["upload", "upload_review", "fail"]


@dataclass(frozen=True)
class Component:
    """One scored check: `score` is 0..1, or None when the check does not apply yet."""

    check_id: str
    score: float | None


def quality_score(components: list[Component], weights: dict[str, float]) -> float:
    """Weighted average (0-100) of the components that apply; 100 when none applies."""
    applicable = [(weights.get(c.check_id, 0.0), c.score) for c in components if c.score is not None]
    total_weight = sum(w for w, _ in applicable)
    if total_weight == 0:
        return 100.0
    return round(100 * sum(w * s for w, s in applicable) / total_weight, 1)


def apply_judge(score: float, problems: list[str], penalties: dict[str, float]) -> float:
    """Takes the judge's penalties (by severity) off the score."""
    return round(max(0.0, score - sum(penalties.get(severity, 0.0) for severity in problems)), 1)


def decide(score: float, hard_failures: list[str], cfg: VerifySettings) -> Outcome:
    if hard_failures or score < cfg.review_at:
        return "fail"
    return "upload" if score >= cfg.upload_at else "upload_review"
