from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from swarm.budget import RunBudget
from swarm.settings import get_settings

log = logging.getLogger("swarm.llm")

_RETRY_HINTS = (
    "tool_choice forces tool use",
    "thinking may not be enabled",
    "forced tool use",
    "thinking.type.enabled",
    "thinking.type.disabled",
    "not supported for this model",
    "sampling parameters",
    "temperature",
)


def format_anthropic_error(exc: BaseException) -> str:
    """Pull the API body out of an SDK exception so logs are actually useful."""
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    message = getattr(exc, "message", None)
    parts = [type(exc).__name__]
    if status is not None:
        parts.append(f"status={status}")
    if message:
        parts.append(str(message))
    else:
        parts.append(str(exc))
    if body is not None:
        try:
            parts.append(json.dumps(body) if not isinstance(body, str) else body)
        except TypeError:
            parts.append(repr(body))
    return " | ".join(parts)


def is_retryable_request_error(text: str) -> bool:
    low = text.lower()
    return any(hint in low for hint in _RETRY_HINTS)


def build_message_kwargs(
    *,
    model: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int,
    judgment: bool,
) -> dict[str, Any]:
    """Build a Messages API payload that Claude 5 will accept.

    Sonnet 5 and Fable 5 turn adaptive thinking on by default. Forced
    ``tool_choice`` plus thinking is a 400 on several of those models
    (always on Fable 5.1). Volume calls disable thinking and keep the
    forced emit tool. Judgment calls leave thinking on, raise the token
    ceiling, and use ``tool_choice=auto``.
    """
    tools = [
        {
            "name": "emit",
            "description": "Return the structured result. You must call this tool.",
            "input_schema": schema,
        }
    ]
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "tools": tools,
    }
    if judgment:
        kwargs["max_tokens"] = max(max_tokens, 12_000)
        kwargs["tool_choice"] = {"type": "auto"}
        kwargs["output_config"] = {"effort": "medium"}
    else:
        kwargs["thinking"] = {"type": "disabled"}
        kwargs["tool_choice"] = {"type": "tool", "name": "emit"}
    return kwargs


def strip_new_api_fields(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Fallback for an old SDK or a model that rejects thinking/effort."""
    out = {k: v for k, v in kwargs.items() if k not in {"thinking", "output_config"}}
    out["tool_choice"] = {"type": "auto"}
    return out


def parse_structured_payload(msg: Any) -> dict[str, Any] | None:
    texts: list[str] = []
    for block in getattr(msg, "content", None) or []:
        kind = getattr(block, "type", None)
        if kind == "tool_use" and getattr(block, "name", None) == "emit":
            data = getattr(block, "input", None)
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    continue
            if isinstance(data, dict):
                return data
        if kind == "text":
            text = getattr(block, "text", None)
            if text:
                texts.append(text)
    for text in texts:
        parsed = _json_object(text)
        if parsed is not None:
            return parsed
    return None


def _json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class LLM:
    def __init__(self, budget: RunBudget) -> None:
        self.budget = budget
        self.settings = get_settings()
        self._client = None
        self.attempts = 0
        self.successes = 0
        self.failures = 0
        self.last_error = ""
        self.run_id = 0
        self.agent = ""
        if self.settings.anthropic_api_key:
            import anthropic

            headers = {}
            if self.settings.anthropic_workspace_id:
                headers["anthropic-workspace-id"] = self.settings.anthropic_workspace_id
            self._client = anthropic.Anthropic(
                api_key=self.settings.anthropic_api_key,
                default_headers=headers or None,
            )

    @property
    def available(self) -> bool:
        return self._client is not None

    def writer_failed(self) -> bool:
        """Key is set, every attempted call failed. Do not publish templates."""
        return self.available and self.attempts > 0 and self.successes == 0

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 4096,
        reserve: bool = False,
        estimate_in: int = 2500,
        estimate_out: int = 1500,
        judgment: bool = False,
    ) -> dict[str, Any] | None:
        if not self.available:
            return None
        model = (
            self.settings.judgment_model if judgment else self.settings.anthropic_model
        )
        estimate = self.budget.estimate_tokens(
            estimate_in, estimate_out, judgment=judgment
        )
        if not self.budget.can_spend(estimate, reserve=reserve):
            log.warning("skipping %s — budget would exceed cap", model)
            return None

        kwargs = build_message_kwargs(
            model=model,
            system=system,
            user=user,
            schema=schema,
            max_tokens=max_tokens,
            judgment=judgment,
        )
        self.attempts += 1
        started = time.perf_counter()
        try:
            msg = self._create(kwargs)
        except Exception as exc:  # noqa: BLE001 — recorded, then fallback
            self.failures += 1
            self.last_error = format_anthropic_error(exc)
            log.error("anthropic call failed model=%s %s", model, self.last_error)
            self._record_call(
                model=model,
                ok=False,
                system=system,
                user=user,
                output="",
                error=self.last_error,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
            return None

        usage = getattr(msg, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) or 0 if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) or 0 if usage else 0
        if usage:
            charged = self.budget.estimate_tokens(in_tok, out_tok, judgment=judgment)
            self.budget.charge(charged)
        else:
            charged = estimate
            self.budget.charge(estimate)

        data = parse_structured_payload(msg)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if data is None:
            self.failures += 1
            stop = getattr(msg, "stop_reason", None)
            self.last_error = f"no structured payload from {model} (stop_reason={stop})"
            log.error("%s", self.last_error)
            self._record_call(
                model=model,
                ok=False,
                system=system,
                user=user,
                output="",
                error=self.last_error,
                latency_ms=latency_ms,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=charged,
            )
            return None
        self.successes += 1
        self._record_call(
            model=model,
            ok=True,
            system=system,
            user=user,
            output=json.dumps(data)[:8000],
            error="",
            latency_ms=latency_ms,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=charged,
        )
        return data

    def _record_call(
        self,
        *,
        model: str,
        ok: bool,
        system: str,
        user: str,
        output: str,
        error: str,
        latency_ms: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        if not self.run_id:
            return
        try:
            from swarm.db import session_scope
            from swarm.orm import AgentCallRow

            blob = f"{system}\n\n{user}"
            with session_scope() as session:
                session.add(
                    AgentCallRow(
                        run_id=self.run_id,
                        agent=self.agent,
                        model=model,
                        ok=ok,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost_usd,
                        latency_ms=latency_ms,
                        error=error,
                        input_text=blob[:8000],
                        output_text=output[:8000],
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("agent_calls write failed: %s", exc)

    def _create(self, kwargs: dict[str, Any]) -> Any:
        try:
            return self._client.messages.create(**kwargs)  # type: ignore[union-attr]
        except TypeError as exc:
            log.warning("SDK rejected request keys, retrying stripped: %s", exc)
            return self._client.messages.create(**strip_new_api_fields(kwargs))  # type: ignore[union-attr]
        except Exception as exc:
            text = format_anthropic_error(exc)
            if not is_retryable_request_error(text):
                raise
            log.warning("retrying without thinking / forced tool_choice: %s", text)
            return self._client.messages.create(**strip_new_api_fields(kwargs))  # type: ignore[union-attr]
