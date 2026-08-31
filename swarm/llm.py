from __future__ import annotations

import json
from typing import Any

from swarm.budget import RunBudget
from swarm.settings import get_settings


class LLM:
    def __init__(self, budget: RunBudget) -> None:
        self.budget = budget
        self.settings = get_settings()
        self._client = None
        if self.settings.anthropic_api_key:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

    @property
    def available(self) -> bool:
        return self._client is not None

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
            self.settings.judgment_model
            if judgment
            else self.settings.anthropic_model
        )
        estimate = self.budget.estimate_tokens(
            estimate_in, estimate_out, judgment=judgment
        )
        if not self.budget.can_spend(estimate, reserve=reserve):
            return None
        try:
            msg = self._client.messages.create(  # type: ignore[union-attr]
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[
                    {
                        "name": "emit",
                        "description": "Return the structured result.",
                        "input_schema": schema,
                    }
                ],
                tool_choice={"type": "tool", "name": "emit"},
            )
        except Exception:
            return None

        usage = getattr(msg, "usage", None)
        if usage:
            self.budget.charge(
                self.budget.estimate_tokens(
                    getattr(usage, "input_tokens", 0) or 0,
                    getattr(usage, "output_tokens", 0) or 0,
                    judgment=judgment,
                )
            )
        else:
            self.budget.charge(estimate)

        for block in msg.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "emit":
                data = block.input
                if isinstance(data, str):
                    return json.loads(data)
                return data
        return None
