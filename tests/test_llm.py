from types import SimpleNamespace

from swarm.budget import RunBudget
from swarm.llm import (
    LLM,
    build_message_kwargs,
    format_anthropic_error,
    is_retryable_request_error,
    parse_structured_payload,
    strip_new_api_fields,
)


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_volume_kwargs_disable_thinking_and_force_emit():
    kw = build_message_kwargs(
        model="claude-sonnet-5",
        system="s",
        user="u",
        schema=SCHEMA,
        max_tokens=4000,
        judgment=False,
    )
    assert kw["thinking"] == {"type": "disabled"}
    assert kw["tool_choice"] == {"type": "tool", "name": "emit"}
    assert "output_config" not in kw


def test_judgment_kwargs_leave_thinking_on():
    kw = build_message_kwargs(
        model="claude-fable-5",
        system="s",
        user="u",
        schema=SCHEMA,
        max_tokens=4000,
        judgment=True,
    )
    assert "thinking" not in kw
    assert kw["tool_choice"] == {"type": "auto"}
    assert kw["max_tokens"] >= 12_000
    assert kw["output_config"]["effort"] == "medium"


def test_strip_drops_forced_tool_and_new_fields():
    kw = build_message_kwargs(
        model="claude-sonnet-5",
        system="s",
        user="u",
        schema=SCHEMA,
        max_tokens=100,
        judgment=False,
    )
    stripped = strip_new_api_fields(kw)
    assert "thinking" not in stripped
    assert stripped["tool_choice"] == {"type": "auto"}


def test_format_error_includes_body():
    exc = SimpleNamespace(
        status_code=400,
        message="invalid_request_error",
        body={"error": {"message": "Thinking may not be enabled when tool_choice forces tool use."}},
    )
    text = format_anthropic_error(exc)  # type: ignore[arg-type]
    assert "400" in text
    assert "tool_choice" in text
    assert is_retryable_request_error(text)


def test_parse_tool_use_and_fenced_json():
    tool = SimpleNamespace(type="tool_use", name="emit", input={"ok": True})
    assert parse_structured_payload(SimpleNamespace(content=[tool])) == {"ok": True}

    text = SimpleNamespace(type="text", text="```json\n{\"ok\": true}\n```")
    assert parse_structured_payload(SimpleNamespace(content=[text])) == {"ok": True}


def test_writer_failed_only_after_attempts():
    llm = LLM(RunBudget(0))
    assert llm.available is False
    assert llm.writer_failed() is False
    llm._client = object()
    llm.attempts = 3
    llm.successes = 0
    llm.failures = 3
    llm.last_error = "status=400"
    assert llm.writer_failed() is True
    llm.successes = 1
    assert llm.writer_failed() is False


def test_retries_forced_tool_400(monkeypatch):
    llm = LLM(RunBudget(5.0))
    llm._client = object()

    class Boom(Exception):
        status_code = 400
        message = "Thinking may not be enabled when tool_choice forces tool use."
        body = None

    calls: list[dict] = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get("tool_choice", {}).get("type") == "tool":
                raise Boom()
            return SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", name="emit", input={"ok": True})],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                stop_reason="tool_use",
            )

    llm._client = SimpleNamespace(messages=FakeMessages())
    data = llm.complete_json(system="s", user="u", schema=SCHEMA)
    assert data == {"ok": True}
    assert len(calls) == 2
    assert calls[1]["tool_choice"] == {"type": "auto"}
    assert llm.successes == 1
    assert llm.writer_failed() is False
