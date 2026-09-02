from swarm.agents.cross_pollinator import _obvious_rejects
from swarm.models import Brief


def test_obvious_rejects_include_run_id():
    briefs = [
        Brief(
            id="a",
            vertical="ai",
            headline="Labs disagree about hospital sales",
            what_is_happening="x",
            why_now="y",
            who_is_affected="z",
        ),
        Brief(
            id="b",
            vertical="health",
            headline="Scribe notes fail discovery",
            what_is_happening="x",
            why_now="y",
            who_is_affected="z",
        ),
    ]
    rows = _obvious_rejects(briefs, run_id=17)
    assert rows
    assert all(row.id.startswith("r17-") for row in rows)
    assert all(not row.accepted for row in rows)
