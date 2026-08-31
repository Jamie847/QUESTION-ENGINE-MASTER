import pytest
from pydantic import ValidationError

from swarm.models import Brief, Coverage, Intersection, Question, Signal
from swarm.taste import load_seed_profile, profile_for_prompt


def test_signal_rejects_empty_title():
    with pytest.raises(ValidationError):
        Signal(source="hn", title="  ")


def test_question_rejects_short_text():
    with pytest.raises(ValidationError):
        Question(id="x", text="Too short?", lens="contrarian")


def test_intersection_requires_scores_in_range():
    with pytest.raises(ValidationError):
        Intersection(
            id="x",
            verticals=["ai", "health"],
            thesis="something",
            surprise=1.4,
            plausibility=0.2,
            coverage=Coverage.thin,
        )


def test_brief_roundtrip():
    b = Brief(
        id="ai-1",
        vertical="ai",
        headline="Labs disagree internally about hospital sales",
        what_is_happening="Safety and sales are shipping different docs.",
        why_now="CIO deals are landing this quarter.",
        who_is_affected="hospital CIOs",
    )
    assert b.velocity.value == "unknown"


def test_seed_taste_is_opinionated():
    profile = load_seed_profile()
    assert len(profile.keep_exemplars) >= 8
    assert len(profile.kill_exemplars) >= 6
    blob = profile_for_prompt(profile)
    assert "implications of" in blob.lower() or "KILL" in blob
    assert "KEEP" in blob
