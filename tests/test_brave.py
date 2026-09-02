from swarm.sources.brave import extract_brave_results


def test_news_endpoint_returns_a_top_level_list():
    payload = {
        "results": [
            {"title": "Hospital CIO pauses scribe rollout", "url": "https://ex.test/a"},
            {"title": "  ", "url": "https://ex.test/skip"},
        ]
    }
    rows = extract_brave_results(payload)
    assert len(rows) == 2
    assert rows[0]["title"].startswith("Hospital")


def test_web_endpoint_nests_results():
    payload = {
        "web": {
            "results": [
                {"title": "Fed holds", "description": "rates", "url": "https://ex.test/b"}
            ]
        }
    }
    rows = extract_brave_results(payload)
    assert rows[0]["title"] == "Fed holds"


def test_news_object_shape_and_empty():
    assert extract_brave_results({"news": {"results": [{"title": "x"}]}})[0]["title"] == "x"
    assert extract_brave_results({}) == []
    assert extract_brave_results({"results": "not-a-list"}) == []
