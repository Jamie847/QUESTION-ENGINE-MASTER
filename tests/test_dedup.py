from swarm.dedup import mark_duplicates, sample_near_miss_pairs, similarity
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


def test_kill_reason_says_lexical_not_semantic():
    a = _q("If ambient voice agents become the default for people over 75, who owns consent?", "a")
    b = _q("If ambient voice agents become the default interface for people over 75, who owns the consent?", "b")
    out = mark_duplicates([a, b], [], threshold=0.58)
    assert "lexical" in out[1].kill_reason
    assert "semantic" not in out[1].kill_reason


def test_near_miss_prefers_shared_verticals_and_ranks_by_overlap():
    today = [
        Question(
            id="t1",
            text="If cash-pay GLP-1 users quit at month 18, which clinics are still priced for forever?",
            lens="second_order",
            verticals=["health", "business"],
            status=QuestionStatus.curated,
        ),
        Question(
            id="t2",
            text="Who writes the playbook for a town that loses its only hospital this year?",
            lens="opportunity",
            verticals=["health"],
            status=QuestionStatus.curated,
        ),
    ]
    prior = [
        Question(
            id="p1",
            text="When the cash-pay GLP-1 cohort drops off after eighteen months, which downstream clinics assumed they stay?",
            lens="second_order",
            verticals=["health", "business"],
            status=QuestionStatus.curated,
        ),
        Question(
            id="p2",
            text="What happens to medical-malpractice discovery when the attending note was drafted by a model?",
            lens="contrarian",
            verticals=["ai", "health"],
            status=QuestionStatus.curated,
        ),
    ]
    pairs = sample_near_miss_pairs(today, prior, n=2)
    assert len(pairs) == 2
    assert pairs[0].share_kind == "intersection"
    assert "health" in pairs[0].shared_verticals
    assert "GLP-1" in pairs[0].today_text or "GLP-1" in pairs[0].prior_text
    assert pairs[0].score < 0.64


def test_near_miss_empty_without_prior_day():
    today = [
        Question(
            id="t1",
            text="If cash-pay GLP-1 users quit at month 18, which clinics are still priced for forever?",
            lens="second_order",
            verticals=["health"],
            status=QuestionStatus.curated,
        )
    ]
    assert sample_near_miss_pairs(today, []) == []
