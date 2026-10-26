"""Quality Score and the Gate decision: worked examples with hand-written expected values."""

import pytest

from mealie_pipeline.scoring import Component, apply_judge, decide, quality_score
from mealie_pipeline.settings import VerifySettings

W: dict[str, float] = {"H3": 20, "S2": 25, "S6": 15, "S1": 15}


def test_weighted_average_of_the_applicable_checks_only():
    # (20*1.0 + 25*0.6 + 15*1.0) / (20+25+15) = 50 / 60 = 83.3. S1 is None: left out, not counted as 0.
    components = [Component("H3", 1.0), Component("S1", None), Component("S2", 0.6), Component("S6", 1.0)]

    assert quality_score(components, W) == 83.3


def test_a_second_worked_example():
    # (20*0.8 + 25*1.0 + 15*0.5) / 60 = (16 + 25 + 7.5) / 60 = 80.8
    components = [Component("H3", 0.8), Component("S2", 1.0), Component("S6", 0.5)]

    assert quality_score(components, W) == 80.8


def test_nothing_applicable_scores_full_marks_and_unknown_checks_weigh_nothing():
    assert quality_score([Component("S4", None)], W) == 100.0
    assert quality_score([Component("S9", 0.0), Component("H3", 1.0)], W) == 100.0


@pytest.mark.parametrize(
    ("score", "problems", "expected"),
    [
        (83.3, [], 83.3),
        (83.3, ["major"], 68.3),  # default penalty 15
        (83.3, ["minor", "minor"], 73.3),  # 5 each
        (83.3, ["blocker"], 53.3),  # 30
        (20.0, ["blocker", "blocker"], 0.0),  # never below zero
    ],
)
def test_judge_penalties(score, problems, expected):
    assert apply_judge(score, problems, VerifySettings().judge_penalties) == expected


@pytest.mark.parametrize(
    ("score", "hard", "outcome"),
    [
        (100, [], "upload"),
        (80, [], "upload"),  # boundary: 80 uploads
        (79.9, [], "upload_review"),
        (60, [], "upload_review"),  # boundary: 60 still uploads, with the review tag
        (59.9, [], "fail"),
        (100, ["H2"], "fail"),  # a hard failure blocks whatever the score
    ],
)
def test_decide(score, hard, outcome):
    assert decide(score, hard, VerifySettings()) == outcome


def test_thresholds_come_from_settings():
    strict = VerifySettings(upload_at=95, review_at=90)

    assert decide(92, [], strict) == "upload_review"
    assert decide(85, [], strict) == "fail"
