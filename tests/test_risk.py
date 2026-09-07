"""Phase 2: beta math and portfolio-weighted beta — hermetic (no network)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.analytics.risk import MIN_OBS, _beta, add_betas, fund_risk_table  # noqa: E402


def _bench(n=120):
    vals = [0.01 if i % 2 == 0 else -0.008 for i in range(n)]
    return pd.Series(vals, index=pd.date_range("2023-01-01", periods=n, freq="B"))


def test_beta_math():
    b = _bench()
    beta, _, r2, n = _beta(2 * b, b)
    assert abs(beta - 2.0) < 1e-9 and abs(r2 - 1.0) < 1e-9 and n == len(b)
    flat = pd.Series(0.0, index=b.index)
    assert abs(_beta(flat, b)[0]) < 1e-9
    # too few overlapping observations -> N/A
    assert np.isnan(_beta(b.iloc[:MIN_OBS - 1], b.iloc[:MIN_OBS - 1])[0])


def test_portfolio_beta_weighting():
    b = _bench()
    rets = pd.DataFrame({"AAA": 2 * b, "BBB": 1 * b, "BENCH": b})
    pos = pd.DataFrame([
        {"fund": "F", "ticker": "AAA", "sec_type": "stock", "bench_ticker": "BENCH",
         "port_w": 0.5, "class_w": 0.5, "market_value": 50.0},
        {"fund": "F", "ticker": "BBB", "sec_type": "stock", "bench_ticker": "BENCH",
         "port_w": 0.5, "class_w": 0.5, "market_value": 50.0},
        {"fund": "F", "ticker": "CASH", "sec_type": "cash", "bench_ticker": "BENCH",
         "port_w": np.nan, "class_w": np.nan, "market_value": 100.0},
    ])
    pos = add_betas(pos, rets)
    assert abs(pos.loc[pos.ticker == "AAA", "beta"].iloc[0] - 2.0) < 1e-9
    assert abs(pos.loc[pos.ticker == "BBB", "beta"].iloc[0] - 1.0) < 1e-9
    assert pos.loc[pos.ticker == "CASH", "beta"].iloc[0] == 0.0

    cfg = {"funds": [{"name": "F", "benchmark": "BENCH"}], "risk": {"beta_window_years": 3}}
    fr = fund_risk_table(pos, rets, cfg).set_index("fund")
    assert abs(fr.loc["F", "beta"] - 0.75) < 1e-9       # (50/200)*2 + (50/200)*1 + (100/200)*0
    assert abs(fr.loc["F", "active_beta"] - 1.5) < 1e-9 # 0.5*2 + 0.5*1
    assert abs(fr.loc["F", "syn_beta"] - 1.5) < 1e-9   # synthetic series cross-check


if __name__ == "__main__":
    test_beta_math()
    test_portfolio_beta_weighting()
    print("OK")
