"""No network calls: exercise persistent cache and competing-worker claims."""
import sqlite3
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from src.ingest import news_analysis as na, research


@pytest.fixture
def store(monkeypatch, tmp_path):
    path = tmp_path / "news.db"
    def connect():
        conn = sqlite3.connect(path, timeout=10)
        conn.execute(na.DDL)
        conn.commit()
        return conn
    monkeypatch.setattr(na, "_connection", connect)
    monkeypatch.setattr(na, "stock_thesis", lambda t: {"thesis": {"date": "2026-10-01", "points": ["Margins expand"]}})
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    return path


ARTICLE = {"id": "a1", "title": "Margins improve", "summary": "Operating margins increased.",
           "publishedAt": "2026-10-03T12:00:00+00:00", "link": "https://example.com/a"}
RESULT = {"classification": "supports", "classificationConfidence": .8,
          "impactScore": 2.1, "impactConfidence": .75}


class ImmediatePool:
    def submit(self, fn, *args):
        fn(*args)


def test_repeat_requests_reuse_durable_result(store, monkeypatch):
    calls = []
    monkeypatch.setattr(na, "_pool", ImmediatePool())
    monkeypatch.setattr(na, "_evaluate", lambda state, model: calls.append(state) or RESULT)
    payload = {"news": [ARTICLE]}
    na.enrich_news("AAPL", payload)
    result = na.enrich_news("AAPL", payload)
    assert len(calls) == 1
    assert result["news"][0]["analysis"]["classification"] == "supports"
    assert result["news"][0]["analysis"]["status"] == "ready"
    assert payload == {"news": [ARTICLE]}  # never mutate Yahoo's shared cache


def test_claim_is_atomic_across_connections(store):
    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda _: na._claim("same-key", "AAPL", {}), range(8)))
    assert sum(t is not None for t in tokens) == 1


def test_content_thesis_and_company_context_invalidate(store, monkeypatch):
    calls = []
    monkeypatch.setattr(na, "_pool", ImmediatePool())
    monkeypatch.setattr(na, "_evaluate", lambda state, model: calls.append(state) or RESULT)
    na.enrich_news("AAPL", {"news": [ARTICLE]})
    na.enrich_news("AAPL", {"news": [{**ARTICLE, "summary": "Corrected margins"}]})
    monkeypatch.setattr(na, "stock_thesis", lambda t: {"thesis": {"points": ["Revenue grows"]}})
    na.enrich_news("AAPL", {"news": [ARTICLE]})
    na.enrich_news("MSFT", {"news": [ARTICLE]})
    assert len(calls) == 4


def test_model_and_rubric_version_invalidate(store, monkeypatch):
    calls = []
    monkeypatch.setattr(na, "_pool", ImmediatePool())
    monkeypatch.setattr(na, "_evaluate", lambda state, model: calls.append(model) or RESULT)
    na.enrich_news("AAPL", {"news": [ARTICLE]})
    monkeypatch.setenv("TYPESAFE_MODEL", "new-version")
    na.enrich_news("AAPL", {"news": [ARTICLE]})
    monkeypatch.setattr(na, "RUBRIC_VERSION", "news-v2")
    na.enrich_news("AAPL", {"news": [ARTICLE]})
    assert len(calls) == 3


def test_no_key_and_database_failure_never_call_jev(store, monkeypatch):
    monkeypatch.setattr(na, "_evaluate", lambda *args: pytest.fail("should not call Jev"))
    monkeypatch.delenv("TYPESAFE_API_KEY")
    assert na.enrich_news("AAPL", {"news": [ARTICLE]})["news"][0]["analysis"]["status"] == "disabled"
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(na, "_connection", lambda: (_ for _ in ()).throw(RuntimeError("db unavailable")))
    assert na.enrich_news("AAPL", {"news": [ARTICLE]})["news"][0]["analysis"]["status"] == "unavailable"


def test_failure_backoff_and_retry_limit(store, monkeypatch):
    calls = []
    monkeypatch.setattr(na, "_pool", ImmediatePool())
    monkeypatch.setattr(na, "_evaluate", lambda *args: calls.append(1) or (_ for _ in ()).throw(RuntimeError("upstream")))
    monkeypatch.setattr(na.time, "time", lambda: 1000)
    na.enrich_news("AAPL", {"news": [ARTICLE]})
    na.enrich_news("AAPL", {"news": [ARTICLE]})
    assert len(calls) == 1
    monkeypatch.setattr(na.time, "time", lambda: 1400)
    na.enrich_news("AAPL", {"news": [ARTICLE]})
    monkeypatch.setattr(na.time, "time", lambda: 1800)
    na.enrich_news("AAPL", {"news": [ARTICLE]})
    monkeypatch.setattr(na.time, "time", lambda: 2200)
    na.enrich_news("AAPL", {"news": [ARTICLE]})
    assert len(calls) == 3


def test_old_claim_cannot_overwrite_recovered_claim(store, monkeypatch):
    monkeypatch.setattr(na.time, "time", lambda: 1000)
    first = na._claim("key", "AAPL", {})
    monkeypatch.setattr(na.time, "time", lambda: 1700)
    second = na._claim("key", "AAPL", {})
    na._finish("key", second, {"status": "ready", "classification": "detracts"})
    na._finish("key", first, {"status": "ready", "classification": "supports"})
    assert na._read("key")["classification"] == "detracts"


def test_unowned_only_ten_articles_and_no_invented_thesis(store, monkeypatch):
    calls = []
    monkeypatch.setattr(na, "stock_thesis", lambda t: {"thesis": None})
    monkeypatch.setattr(na, "_pool", ImmediatePool())
    monkeypatch.setattr(na, "_evaluate", lambda state, model: calls.append(state) or RESULT)
    payload = {"news": [{**ARTICLE, "id": str(i)} for i in range(15)]}
    na.enrich_news("NEW", payload)
    result = na.enrich_news("NEW", payload)
    assert len(calls) == 10
    assert all(not s["thesis"] for s in calls)
    assert result["news"][0]["analysis"]["mode"] == "company"


def test_news_parser_retains_text_dates_deduplicates_and_selects_latest_ten():
    articles = [{"id": str(i), "content": {"title": str(i), "summary": "Summary", "pubDate": f"2026-10-{i:02d}T12:00:00Z"}} for i in range(1, 13)]
    news = research._news(SimpleNamespace(news=[articles[0], {}, *articles]))
    assert len(news) == 10
    assert news[0]["title"] == "12"
    assert news[-1]["title"] == "3"
    assert news[0]["summary"] == "Summary"
    assert news[0]["publishedAt"] == "2026-10-12T12:00:00+00:00"


def test_article_identity_strips_tracking_parameters():
    assert na.article_key({"link": "https://example.com/a?utm_source=yahoo&id=2#fragment"}) == "https://example.com/a?id=2"


def test_status_route_never_fetches_yahoo(monkeypatch):
    from api import main
    monkeypatch.setattr(main.api_cache, "peek", lambda *args: ({"news": [ARTICLE]}, 100))
    monkeypatch.setattr(main, "stock_news", lambda *args: pytest.fail("status poll fetched Yahoo"))
    monkeypatch.setattr(main, "enrich_news", lambda ticker, payload: {**payload, "ticker": ticker})
    assert main.stock_news_analysis_route("aapl")["ticker"] == "AAPL"


def test_news_route_and_status_poll_share_one_assessment(store, monkeypatch):
    from api import main
    calls = []
    payload = {"ticker": "AAPL", "news": [ARTICLE]}
    monkeypatch.setattr(na, "_pool", ImmediatePool())
    monkeypatch.setattr(na, "_evaluate", lambda *args: calls.append(1) or RESULT)
    monkeypatch.setattr(main, "stock_news", lambda t: payload)
    monkeypatch.setattr(main.api_cache, "peek", lambda *args: (payload, 0))
    main.stock_news_route("aapl")
    polled = main.stock_news_analysis_route("aapl")
    reopened = main.stock_news_route("aapl")
    assert len(calls) == 1
    assert polled["news"][0]["analysis"]["status"] == "ready"
    assert reopened["news"][0]["analysis"]["impactConfidence"] == .75


def test_full_queue_is_pending_until_capacity_is_available(store, monkeypatch):
    import threading
    monkeypatch.setattr(na, "_slots", threading.BoundedSemaphore(0))
    monkeypatch.setattr(na, "_evaluate", lambda *args: pytest.fail("full queue should not call Jev"))
    assert na.enrich_news("AAPL", {"news": [ARTICLE]})["news"][0]["analysis"]["status"] == "queued"


def test_real_sdk_request_and_response_contract(store, monkeypatch):
    import httpx2
    import typesafe_sdk
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json={
            "model": na.DEFAULT_MODEL,
            "answers": {
                "direction": {"type": "choice", "choice": "supports", "confidence": .8,
                              "probabilities": {"supports": .85, "detracts": .05, "neutral": .05, "unclear": .05}},
                "impact": {"type": "score", "score": 2.1, "confidence": .75,
                           "probabilities": {"0": 0, "1": 0, "2": .9, "3": .1, "4": 0},
                           "legend": {"0": "Minimal", "1": "Low", "2": "Moderate", "3": "High", "4": "Transformative"}},
            }, "usage": {"input_tokens": 100, "output_tokens": 0},
        })
    original = typesafe_sdk.TypeSafeClient
    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", lambda **kw: original(**kw, transport=httpx2.MockTransport(respond)))
    state = {"ticker": "AAPL", "article": {"title": "Margins improve"}, "thesis": ["Margins expand"]}
    result = na._evaluate(state, na.DEFAULT_MODEL)
    assert result["classification"] == "supports"
    assert result["impactScore"] == 2.1
    assert requests[0]["model"] == na.DEFAULT_MODEL
    assert requests[0]["questions"]["direction"]["type"] == "choice"
    assert len(requests[0]["questions"]["impact"]["criteria"]) == 5
