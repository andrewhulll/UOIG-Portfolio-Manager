import pytest
import sqlite3
import pandas as pd
import numpy as np
from src.analytics.optimize import _uoig_group, _bench_weights, _bench_sector_groups, _fund_daily, fund_diagnostics, whatif_payload, solve_optimizer, _project_capped_simplex, _solve_qp, _bl_posterior
from src.model import schema

def test_uoig_group():
    assert _uoig_group("INFORMATION TECHNOLOGY") == "TMT"
    assert _uoig_group("COMMUNICATION SERVICES") == "TMT"
    assert _uoig_group("FINANCIALS") == "Financial"
    assert _uoig_group("REAL ESTATE") == "Financial"
    assert _uoig_group("ENERGY") == "IME"
    assert _uoig_group("MATERIALS") == "IME"
    assert _uoig_group("HEALTH CARE") == "Healthcare"
    assert _uoig_group("INDUSTRIALS") == "IME"
    assert _uoig_group("CONSUMER DISCRETIONARY") == "Consumer"
    assert _uoig_group("CONSUMER STAPLES") == "Consumer"
    assert _uoig_group("UNKNOWN") is None
    assert _uoig_group(None) is None

def test_bench_weights():
    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.execute("INSERT INTO benchmark_holdings (index_ticker, ticker, weight, sector, updated) VALUES ('SPY', 'AAPL', 0.05, 'TECH', '2023-01-01')")
    conn.execute("INSERT INTO benchmark_holdings (index_ticker, ticker, weight, sector, updated) VALUES ('SPY', 'MSFT', 0.04, 'TECH', '2023-01-01')")
    conn.commit()

    w = _bench_weights(conn, "SPY")
    assert w["AAPL"] == 0.05
    assert w["MSFT"] == 0.04

    assert _bench_weights(conn, "UNKNOWN") == {}

def test_bench_sector_groups():
    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    # 0.10 Tech (TMT), 0.05 Financials (Financial), 0.05 Real Estate (Financial)
    conn.execute("INSERT INTO benchmark_sectors (index_ticker, sector, weight, updated) VALUES ('SPY', 'INFORMATION TECHNOLOGY', 0.10, '2023-01-01')")
    conn.execute("INSERT INTO benchmark_sectors (index_ticker, sector, weight, updated) VALUES ('SPY', 'FINANCIALS', 0.05, '2023-01-01')")
    conn.execute("INSERT INTO benchmark_sectors (index_ticker, sector, weight, updated) VALUES ('SPY', 'REAL ESTATE', 0.05, '2023-01-01')")
    conn.execute("INSERT INTO benchmark_sectors (index_ticker, sector, weight, updated) VALUES ('SPY', 'UNKNOWN', 0.05, '2023-01-01')")
    conn.commit()

    s = _bench_sector_groups(conn, "SPY")
    assert s["TMT"] == 0.10
    assert s["Financial"] == 0.10 # Fin + RE
    assert "UNKNOWN" not in s

def test_fund_daily():
    rets = pd.DataFrame({
        "AAPL": [0.01, 0.02],
        "MSFT": [0.02, 0.01]
    }, index=pd.DatetimeIndex(["2023-01-01", "2023-01-02"]))

    weights = {"AAPL": 0.6, "MSFT": 0.4}

    fd = _fund_daily(rets, weights)
    assert len(fd) == 2
    assert fd.iloc[0] == pytest.approx(0.6*0.01 + 0.4*0.02)

def test_fund_diagnostics(monkeypatch):
    import src.analytics.optimize as opt
    import src.analytics.pnl as pnl

    # Mock daily_returns_matrix to avoid reading from DB which lacks history
    monkeypatch.setattr(opt, "daily_returns_matrix", lambda c, y: pd.DataFrame({
        "AAPL": [0.01, -0.01],
        "MSFT": [-0.01, 0.01],
        "SPY": [0.005, -0.005]
    }, index=pd.DatetimeIndex(["2023-01-01", "2023-01-02"])))

    monkeypatch.setattr(opt, "load_positions", lambda *args, **kwargs: pd.DataFrame({
        "fund": ["FundA", "FundA"],
        "ticker": ["AAPL", "MSFT"],
        "name": ["Apple Inc", "Microsoft Corp"],
        "sec_type": ["stock", "stock"],
        "port_w": [0.60, 0.40],
        "sector": ["INFORMATION TECHNOLOGY", "INFORMATION TECHNOLOGY"],
        "mv": [6000.0, 4000.0]
    }))

    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.execute("INSERT INTO benchmark_holdings (index_ticker, ticker, weight, sector, updated) VALUES ('SPY', 'AAPL', 0.06, 'TECH', '2023-01-01')")
    conn.execute("INSERT INTO benchmark_sectors (index_ticker, sector, weight, updated) VALUES ('SPY', 'INFORMATION TECHNOLOGY', 0.20, '2023-01-01')")
    # Need prices for metrics
    conn.execute("INSERT INTO prices (ticker, date, close, adj_close, source) VALUES ('AAPL', '2023-01-01', 100, 100, 'yfinance')")
    conn.execute("INSERT INTO prices (ticker, date, close, adj_close, source) VALUES ('AAPL', '2023-01-02', 105, 105, 'yfinance')")
    conn.execute("INSERT INTO benchmarks (index_ticker, date, close) VALUES ('SPY', '2023-01-01', 100)")
    conn.execute("INSERT INTO benchmarks (index_ticker, date, close) VALUES ('SPY', '2023-01-02', 101)")
    conn.execute("INSERT INTO benchmarks (index_ticker, date, close) VALUES ('BIL', '2023-01-01', 100)")
    conn.execute("INSERT INTO benchmarks (index_ticker, date, close) VALUES ('BIL', '2023-01-02', 100.1)")
    conn.commit()

    cfg = {"funds": [{"name": "FundA", "benchmark": "SPY"}], "optimization": {"risk_free": "BIL"}}

    diag = fund_diagnostics(cfg, conn, "FundA")
    assert diag["fund"] == "FundA"
    assert diag["benchmark"] == "SPY"

    aapl_w = next(w for w in diag["risk_contribution"] if w["t"] == "AAPL")
    assert aapl_w["port_w"] == pytest.approx(60.0)
    assert aapl_w["bench_w"] == pytest.approx(6.0)
    assert aapl_w["active_w"] == pytest.approx(54.0)

def test_project_capped_simplex():
    # Simple cases
    v = np.array([0.5, 0.5])
    p = _project_capped_simplex(v, 1.0)
    assert np.allclose(p, v)

    v2 = np.array([1.5, -0.5])
    p2 = _project_capped_simplex(v2, 1.0)
    assert np.allclose(p2, [1.0, 0.0])

def test_solve_qp():
    # Min x^2 + y^2 s.t. x+y=1, 0<=x,y<=1
    H = np.eye(2)
    a = np.zeros(2)
    x = _solve_qp(a, H, 1.0)
    assert np.allclose(x, [0.5, 0.5], atol=1e-3)

def test_bl_posterior():
    pi = np.array([0.05, 0.06])
    sigma = np.array([[0.04, 0.02], [0.02, 0.05]])
    views = [{"t": "AAPL", "q": 0.10, "conf": "high"}]
    tickers = ["AAPL", "MSFT"]

    post_mu = _bl_posterior(pi, sigma, views, tickers, 0.05)
    assert post_mu.shape == (2,)


def test_whatif_payload(monkeypatch):
    import src.analytics.optimize as opt

    def mock_book_cached(*args):
        return {
            "cov": np.eye(3),
            "tradable": ["AAPL", "MSFT"],
            "names": {"AAPL": "Apple", "MSFT": "Microsoft"},
            "groups": {"AAPL": "TMT", "MSFT": "TMT"},
            "stock_w": {"AAPL": 0.6, "MSFT": 0.4},
            "bench_w": {"AAPL": 0.1, "MSFT": 0.1},
            "bench": "SPY",
            "overlay": 0.0,
            "inert": 0.0,
            "excluded": [],
            "invested_value": 10000.0
        }

    monkeypatch.setattr(opt, "_book_cached", mock_book_cached)

    conn = sqlite3.connect(":memory:")
    cfg = {}

    res = whatif_payload(cfg, conn, "FundA")
    assert res["fund"] == "FundA"
    assert res["benchmark"] == "SPY"
    assert len(res["stocks"]) == 2
    assert res["stocks"][0]["t"] == "AAPL"

def test_solve_optimizer(monkeypatch):
    import src.analytics.optimize as opt

    def mock_book_cached(*args):
        cov = np.eye(3) * 0.04
        return {
            "cov": cov,
            "tradable": ["AAPL", "MSFT"],
            "names": {"AAPL": "Apple", "MSFT": "Microsoft"},
            "groups": {"AAPL": "TMT", "MSFT": "TMT"},
            "stock_w": {"AAPL": 0.6, "MSFT": 0.4},
            "bench_w": {"AAPL": 0.1, "MSFT": 0.1},
            "bench": "SPY",
            "overlay": 0.0,
            "inert": 0.0,
            "excluded": [],
            "invested_value": 10000.0
        }

    monkeypatch.setattr(opt, "_book_cached", mock_book_cached)
    monkeypatch.setattr(opt, "_risk_free", lambda *args: 0.05)

    conn = sqlite3.connect(":memory:")
    cfg = {}

    res = solve_optimizer(cfg, conn, "FundA")
    assert res["fund"] == "FundA"
    assert "stats" in res
    assert "frontier" in res
    assert "rows" in res
