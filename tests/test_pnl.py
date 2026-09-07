"""Phase 1: P&L engine math — hermetic (no network).

Seeds a throwaway DB from the workbook, injects synthetic live prices and a
dividend, then asserts the computed P&L behaves correctly.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.model import db as _db  # noqa: E402
_db.database_url = lambda: None  # hermetic: always use the throwaway SQLite file

import numpy as np  # noqa: E402

from src.analytics.pnl import fund_summary, load_positions  # noqa: E402
from src.config import load_config  # noqa: E402
from src.io.import_xlsx import import_workbook  # noqa: E402
from src.model.schema import get_connection  # noqa: E402


def _seed(tmp: str) -> dict:
    cfg = load_config()
    cfg["database"] = str(Path(tmp) / "t.db")
    import_workbook(cfg)
    conn = get_connection(cfg["database"])
    # synthetic live prices for AAPL: prev=100, latest=110 (override snapshot)
    conn.executemany(
        "INSERT OR REPLACE INTO prices (ticker, date, close, adj_close, source)"
        " VALUES (?, ?, ?, ?, 'yfinance')",
        [("AAPL", "2026-06-24", 100.0, 100.0), ("AAPL", "2026-06-25", 110.0, 110.0)],
    )
    # a dividend after AAPL's entry date (2022-01-27)
    conn.execute("INSERT OR REPLACE INTO dividends (ticker, ex_date, amount)"
                 " VALUES ('AAPL', '2023-05-01', 1.0)")
    conn.commit()
    conn.close()
    return cfg


def test_pnl_math():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _seed(tmp)
        df = load_positions(cfg)

    aapl = df[(df.fund == "Tall Firs") & (df.ticker == "AAPL")].iloc[0]
    assert abs(aapl.price - 110.0) < 1e-9          # live price beats snapshot
    assert abs(aapl.prev_close - 100.0) < 1e-9
    assert abs(aapl.unreal_pnl_pct - (110.0 / 170.0 - 1)) < 1e-9  # entry 170 from sheet
    assert abs(aapl.day_chg - aapl.shares * 10.0) < 1e-6
    assert aapl.total_ret_pct > aapl.unreal_pnl_pct  # dividend lifts total return

    non_stock = df[df.sec_type != "stock"]
    assert non_stock.unreal_pnl_pct.isna().all()     # index & cash: no entry-based P&L

    sums = df[df.sec_type != "cash"].groupby("fund").port_w.sum()
    assert np.allclose(sums.values, 1.0, atol=1e-9)  # portfolio weights sum to 100%

    fs = fund_summary(df).set_index("fund")
    tf = df[(df.fund == "Tall Firs") & (df.sec_type == "stock")]
    assert abs(fs.loc["Tall Firs", "unreal_pnl"]
               - (tf.market_value.sum() - tf.cost_basis.sum())) < 1e-6


if __name__ == "__main__":
    test_pnl_math()
    print("OK")
