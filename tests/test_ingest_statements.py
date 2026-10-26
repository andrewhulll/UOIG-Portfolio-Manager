import json

import pandas as pd
import pytest

from src.ingest import statements as st


def _df(data: dict, cols):
    """rows -> {name: [values newest..oldest]}; columns are quarter/year-end dates."""
    return pd.DataFrame(data, index=pd.to_datetime(cols)).T


# Sep fiscal year-end, like Apple: FY2025 ended 2025-09-30.
Q_COLS = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
A_COLS = ["2025-09-30", "2024-09-30"]


def _q_income():
    return pd.DataFrame(
        {
            "Total Revenue": [120.0, 110.0, 100.0, 90.0, 80.0],
            "Gross Profit": [60.0, 55.0, 50.0, 45.0, 40.0],
            "Operating Income": [30.0, 27.0, 25.0, 22.0, 20.0],
            "Pretax Income": [28.0, 26.0, 24.0, 21.0, 19.0],
            "Tax Provision": [5.6, 5.2, 4.8, 4.2, 3.8],
            "Net Income": [22.4, 20.8, 19.2, 16.8, 15.2],
            "EBITDA": [36.0, 33.0, 30.0, 27.0, 24.0],
            "Diluted EPS": [2.0, 1.9, 1.7, 1.5, 1.4],
            "Odd Custom Line": [1.0, 1.0, 1.0, 1.0, 1.0],
        },
        index=pd.to_datetime(Q_COLS),
    ).T


def _q_balance():
    return pd.DataFrame(
        {
            "Total Assets": [500.0, 480.0, 470.0, 460.0, 450.0],
            "Current Assets": [200.0, 190.0, 180.0, 170.0, 160.0],
            "Current Liabilities": [100.0, 100.0, 95.0, 90.0, 90.0],
            "Stockholders Equity": [250.0, 240.0, 230.0, 220.0, 210.0],
            "Total Debt": [100.0, 100.0, 100.0, 100.0, 100.0],
            "Net Debt": [40.0, 45.0, 50.0, 55.0, 60.0],
            "Ordinary Shares Number": [98.0, 99.0, 100.0, 101.0, 102.0],
        },
        index=pd.to_datetime(Q_COLS),
    ).T


def _q_cashflow():
    return pd.DataFrame(
        {
            "Operating Cash Flow": [30.0, 28.0, 26.0, 24.0, 22.0],
            "Capital Expenditure": [-4.0, -4.0, -4.0, -4.0, -4.0],
            "Free Cash Flow": [26.0, 24.0, 22.0, 20.0, 18.0],
            "Cash Dividends Paid": [-3.0, -3.0, -3.0, -3.0, -3.0],
            "Repurchase Of Capital Stock": [-10.0, -10.0, -10.0, -10.0, -10.0],
        },
        index=pd.to_datetime(Q_COLS),
    ).T


def _a_income():
    return pd.DataFrame(
        {"Total Revenue": [400.0, 330.0], "Net Income": [72.0, 60.0], "Gross Profit": [190.0, 150.0],
         "Operating Income": [95.0, 75.0], "Pretax Income": [90.0, 72.0], "Tax Provision": [18.0, 14.4]},
        index=pd.to_datetime(A_COLS),
    ).T


def _a_balance():
    return pd.DataFrame(
        {"Total Assets": [460.0, 420.0], "Stockholders Equity": [220.0, 200.0],
         "Total Debt": [100.0, 110.0], "Ordinary Shares Number": [101.0, 104.0]},
        index=pd.to_datetime(A_COLS),
    ).T


def _a_cashflow():
    return pd.DataFrame(
        {"Free Cash Flow": [80.0, 70.0], "Capital Expenditure": [-16.0, -14.0]},
        index=pd.to_datetime(A_COLS),
    ).T


class FakeTicker:
    def __init__(self, **overrides):
        self.income_stmt = _a_income()
        self.quarterly_income_stmt = _q_income()
        self.balance_sheet = _a_balance()
        self.quarterly_balance_sheet = _q_balance()
        self.cashflow = _a_cashflow()
        self.quarterly_cashflow = _q_cashflow()
        self.info = {"currency": "USD", "financialCurrency": "USD", "marketCap": 1e12,
                     "trailingPE": 30.0, "priceToBook": 40.0, "enterpriseValue": 1.1e12,
                     "enterpriseToEbitda": 25.0}
        self.earnings_estimate = pd.DataFrame(
            {"avg": [2.1, 2.5, 8.8, 9.6], "low": [2.0, 2.2, 8.3, 8.5], "high": [2.2, 2.9, 8.9, 10.7],
             "yearAgoEps": [1.85, 2.84, 7.46, 8.8], "numberOfAnalysts": [27, 21, 39, 40],
             "growth": [0.07, 0.02, 0.18, 0.08], "currency": ["USD"] * 4},
            index=["0q", "+1q", "0y", "+1y"])
        self.revenue_estimate = pd.DataFrame(
            {"avg": [1.2e11, 1.5e11, 4.8e11, 5.3e11], "low": [1.1e11] * 4, "high": [1.3e11] * 4,
             "numberOfAnalysts": [25, 20, 38, 39], "yearAgoRevenue": [1.0e11] * 4,
             "growth": [0.1, 0.07, 0.15, 0.1], "currency": ["USD"] * 4},
            index=["0q", "+1q", "0y", "+1y"])
        self.eps_trend = pd.DataFrame(
            {"current": [2.1, 2.5], "7daysAgo": [2.1, 2.5], "30daysAgo": [2.0, 2.4],
             "60daysAgo": [1.9, 2.3], "90daysAgo": [1.8, 2.2]}, index=["0q", "0y"])
        self.earnings_history = pd.DataFrame(
            {"epsActual": [1.85, 1.9], "epsEstimate": [1.77, 1.95], "epsDifference": [0.08, -0.05],
             "surprisePercent": [0.045, -0.026]},
            index=pd.to_datetime(["2025-09-30", "2025-12-31"]))
        self.growth_estimates = pd.DataFrame(
            {"stockTrend": [0.07, 0.15], "indexTrend": [0.26, 0.12]}, index=["0q", "LTG"])
        self.analyst_price_targets = {"current": 100.0, "low": 80.0, "mean": 120.0, "median": 118.0, "high": 150.0}
        self.recommendations_summary = pd.DataFrame(
            {"period": ["0m", "-1m"], "strongBuy": [6, 5], "buy": [18, 17], "hold": [14, 15],
             "sell": [3, 3], "strongSell": [3, 3]})
        self.upgrades_downgrades = pd.DataFrame(
            {"Firm": ["Loop Capital", "JP Morgan", "Needham"], "ToGrade": ["Hold", "Overweight", "Hold"],
             "FromGrade": ["Buy", "Overweight", "Hold"], "Action": ["down", "main", "reit"],
             "priceTargetAction": ["Lowers", "Raises", ""],
             "currentPriceTarget": [330.0, 360.0, 0.0], "priorPriceTarget": [370.0, 340.0, 0.0]},
            index=pd.to_datetime(["2026-10-20 09:46:57", "2026-10-12 18:47:46", "2026-10-01 11:00:30"]))
        for k, v in overrides.items():
            setattr(self, k, v)


def _build(**overrides):
    return st.build_statements("TEST", FakeTicker(**overrides))


# ---------- helpers ----------
def test_fiscal_labels_follow_the_fiscal_year_end():
    # Sep FYE: the Dec quarter belongs to the next fiscal year's Q1.
    assert st._quarter_label("2025-12-31", 9) == "Q1 FY26"
    assert st._quarter_label("2026-09-30", 9) == "Q4 FY26"
    assert st._annual_label("2025-09-30", 9) == "FY2025"
    # Dec FYE is calendar.
    assert st._quarter_label("2026-03-31", 12) == "Q1 FY26"
    # March FYE (Toyota): Jun 2026 is Q1 of FY2027.
    assert st._quarter_label("2026-06-30", 3) == "Q1 FY27"
    assert st._annual_label("2026-03-31", 3) == "FY2026"


def test_pick_skips_nan_and_falls_back_to_alias():
    s = pd.Series({"Total Revenue": float("nan"), "Operating Revenue": 7.0})
    assert st._pick(s, ("Total Revenue", "Operating Revenue")) == 7.0
    assert st._pick(None, ("x",)) is None
    assert st._pick(s, ("Missing",)) is None


# ---------- statements ----------
def test_statement_rows_periods_and_other_bucket():
    p = _build()
    inc = p["statements"]["income"]
    q = inc["quarterly"]
    assert q["periods"] == ["Q3 FY26", "Q2 FY26", "Q1 FY26", "Q4 FY25", "Q3 FY25"]
    rev = next(r for r in q["rows"] if r["key"] == "revenue")
    assert rev["vals"] == [120.0, 110.0, 100.0, 90.0, 80.0]
    assert rev["level"] == 0
    # Rows with no data anywhere (e.g. R&D here) are dropped, not shown as dashes.
    assert "rnd" not in [r["key"] for r in q["rows"]]
    # Unmapped Yahoo lines are kept so no data is lost.
    assert [r["label"] for r in q["other"]] == ["Odd Custom Line"]
    assert inc["annual"]["periods"] == ["FY2025", "FY2024"]


def test_ttm_sums_flows_and_takes_latest_stock():
    p = _build()
    ttm = p["statements"]["income"]["ttm"]
    assert ttm["period"] == "TTM Jun-26"
    assert ttm["vals"]["revenue"] == 120 + 110 + 100 + 90
    assert ttm["vals"]["dilutedEps"] == pytest.approx(2.0 + 1.9 + 1.7 + 1.5)
    # Balance-sheet rows are point-in-time: the latest quarter, not a sum.
    assert p["statements"]["balance"]["ttm"]["vals"]["totalAssets"] == 500.0


def test_sparse_latest_quarter_does_not_break_ttm():
    # Yahoo sometimes appends a just-reported quarter that only has EPS (seen on JPM).
    q = _q_income()
    q.insert(0, pd.Timestamp("2026-09-30"), float("nan"))
    q.loc["Diluted EPS", pd.Timestamp("2026-09-30")] = 2.2
    p = _build(quarterly_income_stmt=q)
    ttm = p["statements"]["income"]["ttm"]
    assert ttm["period"] == "TTM Jun-26"
    assert ttm["vals"]["revenue"] == 420.0
    # The sparse column is still shown as a period.
    assert p["statements"]["income"]["quarterly"]["periods"][0] == "Q4 FY26"


def test_ttm_needs_four_quarters_for_a_row():
    q = _q_income()
    q.loc["Gross Profit", q.columns[3]] = float("nan")
    ttm = _build(quarterly_income_stmt=q)["statements"]["income"]["ttm"]
    assert "grossProfit" not in ttm["vals"]      # a 3-quarter sum would understate it
    assert "revenue" in ttm["vals"]


def test_missing_statement_degrades_to_partial():
    p = _build(balance_sheet=None, quarterly_balance_sheet=pd.DataFrame())
    assert "balance" not in p["statements"]
    assert "statements.balance" in p["partial"]
    assert p["statements"]["income"]          # the rest still resolves


def test_missing_annual_only_is_flagged():
    p = _build(income_stmt=None)
    assert "statements.income.annual" in p["partial"]
    assert "annual" not in p["statements"]["income"]
    assert "quarterly" in p["statements"]["income"]


def test_tk_attribute_errors_do_not_raise():
    class Boom(FakeTicker):
        @property
        def cashflow(self):
            raise RuntimeError("HTTP 404")

        @cashflow.setter
        def cashflow(self, _):
            pass

    p = st.build_statements("TEST", Boom())
    assert "annual" not in p["statements"]["cashflow"]


# ---------- ratios ----------
def test_annual_ratios():
    r = {x["key"]: x["vals"][0] for x in _build()["ratios"]["annual"]["rows"]}
    assert r["grossMargin"] == pytest.approx(190 / 400)
    assert r["netMargin"] == pytest.approx(72 / 400)
    assert r["roe"] == pytest.approx(72 / 220)
    assert r["fcfMargin"] == pytest.approx(80 / 400)
    assert r["capexPctRevenue"] == pytest.approx(16 / 400)
    assert r["debtToEquity"] == pytest.approx(100 / 220)
    # NOPAT = 95 * (1 - 18/90); invested capital = debt + equity.
    assert r["roic"] == pytest.approx(95 * (1 - 0.2) / 320)
    # Share count vs the prior fiscal year.
    assert r["sharesChange"] == pytest.approx(101 / 104 - 1)


def test_roic_ignores_yahoo_invested_capital_row():
    b = _q_balance()
    b.loc["Invested Capital"] = 2.0   # the broken value Yahoo returned for ASML
    ttm = _build(quarterly_balance_sheet=b)["ratios"]["ttm"]["vals"]
    assert ttm["roic"] < 1.0


def test_ttm_ratios_use_summed_flows_and_latest_balance():
    ttm = _build()["ratios"]["ttm"]["vals"]
    assert ttm["netMargin"] == pytest.approx((22.4 + 20.8 + 19.2 + 16.8) / 420)
    assert ttm["roe"] == pytest.approx((22.4 + 20.8 + 19.2 + 16.8) / 250)


def test_quarterly_ratios_skip_return_metrics():
    keys = [x["key"] for x in _build()["ratios"]["quarterly"]["rows"]]
    assert "netMargin" in keys
    assert not {"roe", "roa", "roic"} & set(keys)


def test_ratio_division_by_zero_is_none():
    assert st._div(1.0, 0) is None
    assert st._div(None, 2) is None


def test_bank_gets_no_fcf_ratios_and_flag():
    bank_q = pd.DataFrame(
        {"Total Revenue": [50.0, 48.0, 46.0, 44.0, 42.0], "Net Interest Income": [25.0] * 5,
         "Net Income": [15.0, 14.0, 13.0, 12.0, 11.0], "Pretax Income": [20.0] * 5},
        index=pd.to_datetime(Q_COLS)).T
    p = _build(income_stmt=bank_q.iloc[:, :2], quarterly_income_stmt=bank_q)
    assert p["isBank"] is True
    keys = {x["key"] for x in p["ratios"]["annual"]["rows"]}
    assert "netMargin" in keys
    assert not keys & {"fcfMargin", "fcfConversion", "currentRatio", "roic", "grossMargin"}
    assert "fcfMargin" not in p["ratios"]["ttm"]["vals"]
    assert _build()["isBank"] is False


# ---------- valuation / currency ----------
def test_valuation_and_currency():
    p = _build()
    assert p["currency"] == {"reporting": "USD", "trading": "USD"}
    assert p["valuation"]["trailingPE"] == 30.0
    assert p["valuation"]["priceToBook"] == 40.0


def test_currency_mismatch_drops_corrupted_multiples():
    # ASML: USD price over EUR financials gave P/B of 1,349 and EV/EBITDA of 2,066.
    info = {"currency": "USD", "financialCurrency": "EUR", "marketCap": 6e11, "trailingPE": 38.0,
            "priceToBook": 1349.0, "enterpriseToEbitda": 2066.0, "enterpriseValue": 3.3e13,
            "enterpriseToRevenue": 847.0}
    v = _build(info=info)["valuation"]
    assert v["trailingPE"] == 38.0
    assert not {"priceToBook", "evToEbitda", "evToRevenue", "enterpriseValue"} & set(v)


def test_info_failure_is_partial_not_fatal():
    class NoInfo(FakeTicker):
        @property
        def info(self):
            raise RuntimeError("429")

        @info.setter
        def info(self, _):
            pass

    p = st.build_statements("TEST", NoInfo())
    assert p["valuation"] is None and p["currency"] is None
    assert "valuation" in p["partial"]
    assert p["statements"]


# ---------- consensus ----------
def test_estimate_periods_use_real_fiscal_labels():
    est = _build()["consensus"]["estimates"]
    # Latest actual quarter is Jun-26 (Q3 FY26) -> next is Q4 FY26, then Q1 FY27.
    assert [e["period"] for e in est] == ["Q4 FY26E", "Q1 FY27E", "FY2026E", "FY2027E"]
    fy = est[2]
    assert fy["eps"] == {"avg": 8.8, "low": 8.3, "high": 8.9, "yearAgo": 7.46, "growth": 0.18}
    assert fy["revenue"]["yearAgo"] == 1.0e11
    assert fy["analysts"] == 39


def test_surprises_sorted_oldest_first_with_fiscal_labels():
    sp = _build()["consensus"]["surprises"]
    assert [s["period"] for s in sp] == ["Q4 FY25", "Q1 FY26"]
    assert sp[0]["surprisePct"] == 0.045


def test_revisions_growth_targets_and_rating_trend():
    c = _build()["consensus"]
    assert c["revisions"][0] == {"key": "0q", "period": "Q4 FY26E", "current": 2.1,
                                 "d7": 2.1, "d30": 2.0, "d60": 1.9, "d90": 1.8}
    assert [g["period"] for g in c["growth"]] == ["Q4 FY26E", "Long-term"]
    assert c["targets"]["mean"] == 120.0
    assert c["ratingTrend"][0] == {"period": "0m", "strongBuy": 6, "buy": 18, "hold": 14,
                                   "sell": 3, "strongSell": 3, "total": 44}


def test_broker_log_newest_first_zero_target_is_null_and_limited():
    log = _build()["consensus"]["brokerLog"]
    assert [r["firm"] for r in log] == ["Loop Capital", "JP Morgan", "Needham"]
    assert log[0]["date"] == "2026-10-20"
    assert (log[0]["target"], log[0]["priorTarget"], log[0]["targetAction"]) == (330.0, 370.0, "Lowers")
    assert log[2]["target"] is None and log[2]["priorTarget"] is None
    assert len(st.build_statements("T", FakeTicker(), broker_limit=2)["consensus"]["brokerLog"]) == 2


def test_uncovered_name_has_no_consensus_but_keeps_statements():
    p = _build(earnings_estimate=None, revenue_estimate=None, eps_trend=None, earnings_history=None,
               growth_estimates=None, analyst_price_targets={}, recommendations_summary=None,
               upgrades_downgrades=pd.DataFrame())
    assert p["consensus"] is None
    assert "consensus" in p["partial"]
    assert p["statements"]


def test_one_failing_consensus_section_is_isolated():
    class BadRatings(FakeTicker):
        @property
        def recommendations_summary(self):
            raise RuntimeError("boom")

        @recommendations_summary.setter
        def recommendations_summary(self, _):
            pass

    p = st.build_statements("TEST", BadRatings())
    assert p["consensus"]["estimates"]
    assert p["consensus"]["ratingTrend"] == []
    assert "consensus.ratingTrend" in p["partial"]


# ---------- payload ----------
def test_payload_is_json_safe_and_has_no_nan():
    p = _build()
    text = json.dumps(p, allow_nan=False)   # raises on NaN / Infinity
    assert "NaN" not in text
    assert p["ticker"] == "TEST"
    assert p["fiscalYearEndMonth"] == 9


def test_has_data_requires_a_resolved_section():
    assert st.has_data(_build())
    empty = st.build_statements("X", FakeTicker(
        income_stmt=None, quarterly_income_stmt=None, balance_sheet=None, quarterly_balance_sheet=None,
        cashflow=None, quarterly_cashflow=None, info={}, earnings_estimate=None, revenue_estimate=None,
        eps_trend=None, earnings_history=None, growth_estimates=None, analyst_price_targets={},
        recommendations_summary=None, upgrades_downgrades=pd.DataFrame()))
    assert not st.has_data(empty)


# ---------- cached access ----------
class FakeCache:
    """In-memory stand-in for src.model.cache with its get/peek TTL semantics."""
    MISS = object()

    def __init__(self):
        self.rows = {}        # (ns, key) -> (value, ttl)
        self.expired = set()  # rows that exist but are past their TTL

    def get(self, ns, key):
        if (ns, key) in self.rows and (ns, key) not in self.expired:
            return self.rows[(ns, key)][0], 5.0
        return self.MISS

    def peek(self, ns, key):
        return (self.rows[(ns, key)][0], 99999.0) if (ns, key) in self.rows else self.MISS

    def set(self, ns, key, value, ttl):
        self.rows[(ns, key)] = (value, ttl)
        self.expired.discard((ns, key))


@pytest.fixture
def fake_cache(monkeypatch):
    fc = FakeCache()
    monkeypatch.setattr(st, "cache", fc)
    st._CACHE.clear()
    yield fc
    st._CACHE.clear()


def _stub_build(monkeypatch, payloads):
    calls = []

    def fake(ticker, tk=None, **_kw):
        calls.append(ticker)
        return payloads[min(len(calls), len(payloads)) - 1]
    monkeypatch.setattr(st, "build_statements", fake)
    return calls


GOOD = {"ticker": "JPM", "statements": {"income": {}}, "consensus": None, "valuation": None, "partial": []}
EMPTY = {"ticker": "JPM", "statements": None, "consensus": None, "valuation": None, "partial": ["x"]}


def test_stock_statements_caches_and_reuses(monkeypatch, fake_cache):
    calls = _stub_build(monkeypatch, [GOOD])
    assert st.stock_statements("jpm") == GOOD
    assert st.stock_statements("JPM") == GOOD
    assert calls == ["JPM"]                                   # second read hit memory
    assert fake_cache.rows[("statements", "JPM")][1] == 21600  # 6h TTL


def test_stock_statements_reads_shared_cache_before_fetching(monkeypatch, fake_cache):
    calls = _stub_build(monkeypatch, [GOOD])
    fake_cache.set("statements", "JPM", {**GOOD, "from": "db"}, 21600)
    assert st.stock_statements("JPM")["from"] == "db"
    assert calls == []


def test_failed_fetch_is_not_cached_and_serves_stale(monkeypatch, fake_cache):
    fake_cache.set("statements", "JPM", GOOD, 21600)
    fake_cache.expired.add(("statements", "JPM"))
    _stub_build(monkeypatch, [EMPTY])
    out = st.stock_statements("JPM")
    assert out["stale"] is True and out["statements"]
    assert fake_cache.rows[("statements", "JPM")][0] == GOOD   # good data untouched


def test_failed_fetch_with_no_prior_copy_returns_payload_uncached(monkeypatch, fake_cache):
    _stub_build(monkeypatch, [EMPTY, GOOD])
    assert st.stock_statements("JPM") == EMPTY
    assert ("statements", "JPM") not in fake_cache.rows
    assert st.stock_statements("JPM") == GOOD                  # next request retries


def test_snapshot_refresh_never_overwrites_with_empty(monkeypatch, fake_cache):
    _stub_build(monkeypatch, [GOOD, EMPTY])
    st.refresh_statements_snapshot("jpm")
    assert fake_cache.rows[("stock_statements", "JPM")] == (GOOD, 2592000)
    st.refresh_statements_snapshot("JPM")
    assert fake_cache.rows[("stock_statements", "JPM")][0] == GOOD


def test_snapshot_read_never_builds_and_allows_stale(monkeypatch, fake_cache):
    monkeypatch.setattr(st, "build_statements", lambda *a, **k: pytest.fail("snapshot read hit yfinance"))
    pending = st.statements_snapshot("aapl")
    assert pending["snapshotPending"] is True and pending["statements"] is None
    fake_cache.set("stock_statements", "AAPL", GOOD, 1)
    fake_cache.expired.add(("stock_statements", "AAPL"))       # peek ignores expiry
    got = st.statements_snapshot("AAPL")
    assert got["snapshotPending"] is False and got["statements"]


# ---------- route ----------
def _db(tmp_path):
    import sqlite3
    from src.model import schema
    path = tmp_path / "s.db"
    conn = sqlite3.connect(path)
    schema.create_schema(conn)
    conn.execute("INSERT INTO securities (ticker, name, sec_type) VALUES ('AAPL', 'Apple', 'stock')")
    conn.execute("INSERT INTO holdings (fund, ticker, shares) VALUES ('Tall Firs', 'AAPL', 10)")
    conn.commit()
    conn.close()
    return path


def test_route_owned_reads_snapshot_only(monkeypatch, tmp_path):
    import sqlite3
    from api import main
    path = _db(tmp_path)
    monkeypatch.setattr(main, "_conn", lambda: sqlite3.connect(path))
    monkeypatch.setattr(main, "statements_snapshot", lambda t: {"ticker": t, "statements": {}})
    monkeypatch.setattr(main, "stock_statements", lambda _t: pytest.fail("owned ticker reached yfinance"))
    assert main.stock_statements_route("aapl") == {"ticker": "aapl", "statements": {}, "owned": True}


def test_route_unowned_fetches_live_and_maps_errors(monkeypatch, tmp_path):
    import sqlite3
    from fastapi import HTTPException
    from api import main
    path = _db(tmp_path)
    monkeypatch.setattr(main, "_conn", lambda: sqlite3.connect(path))
    monkeypatch.setattr(main, "statements_snapshot", lambda _t: pytest.fail("unowned used snapshot"))
    monkeypatch.setattr(main, "stock_statements", lambda t: {"ticker": t})
    assert main.stock_statements_route("jpm") == {"ticker": "JPM", "owned": False}

    def boom(_t):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(main, "stock_statements", boom)
    with pytest.raises(HTTPException) as e:
        main.stock_statements_route("jpm")
    assert e.value.status_code == 502
