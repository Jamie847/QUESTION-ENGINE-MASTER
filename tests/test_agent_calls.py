from types import SimpleNamespace

from sqlalchemy import select

from swarm.budget import RunBudget
from swarm.db import init_db, session_scope
from swarm.llm import LLM
from swarm.orm import AgentCallRow, RunRow


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_successful_call_writes_agent_calls_row():
    init_db()
    with session_scope() as session:
        run = RunRow(status="running", budget_usd=5)
        session.add(run)
        session.flush()
        run_id = run.id

    llm = LLM(RunBudget(5.0))
    llm.run_id = run_id
    llm.agent = "scout"
    llm._client = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **_k: SimpleNamespace(
                content=[
                    SimpleNamespace(type="tool_use", name="emit", input={"ok": True})
                ],
                usage=SimpleNamespace(input_tokens=12, output_tokens=4),
                stop_reason="tool_use",
            )
        )
    )
    assert llm.complete_json(system="sys", user="usr", schema=SCHEMA) == {"ok": True}
    with session_scope() as session:
        rows = list(session.scalars(select(AgentCallRow).where(AgentCallRow.run_id == run_id)))
    assert len(rows) == 1
    assert rows[0].agent == "scout"
    assert rows[0].ok is True
    assert rows[0].input_tokens == 12
    assert rows[0].cost_usd > 0
    assert "usr" in rows[0].input_text
