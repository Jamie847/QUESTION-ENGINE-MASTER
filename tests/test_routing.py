from swarm.sources.routing import contains_keyword, hint_verticals, topic


def test_ai_does_not_match_attention():
    assert not contains_keyword("Wikipedia attention: Main Page", "ai")
    assert contains_keyword("Open-weight models undercut analyst retainers", "model")


def test_who_does_not_match_whorehouse():
    assert not contains_keyword("The Best Little Whorehouse in Texas", "who")


def test_sec_does_not_match_security():
    assert not contains_keyword("home security cameras", "sec")
    assert contains_keyword("SEC comment letters on 10-Ks", "sec")


def test_hint_verticals_uses_boundaries():
    cfgs = [
        {"id": "ai", "keywords": ["ai", "model"], "hn_keywords": []},
        {"id": "health", "keywords": ["who", "drug"], "hn_keywords": []},
    ]
    assert hint_verticals("Wikipedia attention: Main Page", cfgs) == []
    assert "ai" in hint_verticals("A new AI agent shipped to hospitals", cfgs)


def test_topic_strips_wikipedia_prefix():
    assert topic("Wikipedia attention: Semaglutide", words=4) == "Semaglutide"
