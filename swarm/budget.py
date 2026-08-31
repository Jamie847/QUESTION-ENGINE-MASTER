from __future__ import annotations


class BudgetExceeded(RuntimeError):
    pass


class RunBudget:
    """Hard dollar cap. Curator + archive are reserved so a spendy
    scout cannot starve the quality gate."""

    def __init__(self, limit_usd: float, reserved_usd: float = 0.35) -> None:
        self.limit_usd = max(0.0, limit_usd)
        self.reserved_usd = min(reserved_usd, self.limit_usd)
        self.spent_usd = 0.0
        self.calls = 0

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    def can_spend(self, estimate_usd: float, *, reserve: bool = False) -> bool:
        if self.limit_usd <= 0:
            return False
        floor = 0.0 if reserve else self.reserved_usd
        return (self.spent_usd + estimate_usd) <= (self.limit_usd - floor) or (
            reserve and self.spent_usd + estimate_usd <= self.limit_usd
        )

    def charge(self, usd: float) -> None:
        self.spent_usd += max(0.0, usd)
        self.calls += 1
        if self.spent_usd > self.limit_usd + 0.01:
            raise BudgetExceeded(
                f"run budget exceeded: ${self.spent_usd:.3f} > ${self.limit_usd:.2f}"
            )

    def estimate_tokens(self, input_tokens: int, output_tokens: int) -> float:
        # Sonnet-class ballpark; used for reservation before a call.
        return (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0
