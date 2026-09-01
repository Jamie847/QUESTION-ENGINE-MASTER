from swarm.budget import RunBudget
from swarm.settings import Settings, get_settings


def test_judgment_model_defaults_to_opus():
    get_settings.cache_clear()
    s = Settings()
    assert s.judgment_model.startswith("claude-fable")
    assert s.anthropic_model.startswith("claude-sonnet")
    assert s.judgment_model != s.anthropic_model
    assert s.budget_usd == 5.0


def test_opus_reservation_is_more_expensive():
    budget = RunBudget(3.0)
    sonnet = budget.estimate_tokens(4000, 2000, judgment=False)
    opus = budget.estimate_tokens(4000, 2000, judgment=True)
    assert opus > sonnet * 3
    assert budget.can_spend(opus, reserve=True)
