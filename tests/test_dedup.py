from swarm.dedup import mark_duplicates, similarity
from swarm.models import Question, QuestionStatus


def _q(text: str, qid: str = "x") -> Question:
    return Question(
        id=qid,
        text=text,
        lens="contrarian",
        verticals=["ai"],
    )


def test_near_duplicate_marked():
    a = _q("If ambient voice agents become the default for people over 75, who owns consent?", "a")
    b = _q("If ambient voice agents become the default interface for people over 75, who owns the consent?", "b")
    out = mark_duplicates([a, b], [], threshold=0.58)
    assert out[0].status != QuestionStatus.duplicate
    assert out[1].status == QuestionStatus.duplicate


def test_archive_lookback_catches_repeats():
    prior = ["What happens to medical-malpractice discovery when the attending note was drafted by a model?"]
    q = _q("What happens to medical malpractice discovery when the attending's note was drafted by a model?")
    out = mark_duplicates([q], prior, threshold=0.58)
    assert out[0].status == QuestionStatus.duplicate
    assert out[0].duplicate_of == "archive"


def test_distinct_questions_survive():
    a = _q("If GLP-1 adherence collapses after 18 months for the cash-pay cohort, which clinics are mispriced?", "a")
    b = _q("Who is writing the playbook for towns that lose their only hospital?", "b")
    out = mark_duplicates([a, b], [], threshold=0.58)
    assert all(q.status != QuestionStatus.duplicate for q in out)
    assert similarity(a.text, b.text) < 0.5


def test_shared_template_does_not_force_duplicate():
    a = _q("What if the consensus read of Claude Code Auto Mode is inverted — who is already positioned for the reverse?", "a")
    b = _q("What if the consensus read of Cialis as a longevity drug is inverted — who is already positioned for the reverse?", "b")
    out = mark_duplicates([a, b], [], threshold=0.58)
    assert all(q.status != QuestionStatus.duplicate for q in out)
