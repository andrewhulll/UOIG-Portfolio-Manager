"""Phase 0 guarantee: a fresh import reconciles to the source workbook exactly.

Runs the importer into a throwaway DB, then asserts every market value and
weight matches the original sheet within tolerance.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.model import db as _db  # noqa: E402
_db.database_url = lambda: None  # hermetic: always use the throwaway SQLite file

from scripts.reconcile import MV_TOL, WEIGHT_TOL, reconcile  # noqa: E402
from src.config import load_config  # noqa: E402
from src.io.import_xlsx import import_workbook  # noqa: E402


def test_import_reconciles_to_workbook():
    cfg = load_config()
    with tempfile.TemporaryDirectory() as tmp:
        cfg["database"] = str(Path(tmp) / "test.db")
        import_workbook(cfg)
        report = reconcile(cfg)

    assert report["ok"], "reconciliation failed"
    for name, r in report["funds"].items():
        assert r["total_diff"] <= MV_TOL, f"{name} total off by {r['total_diff']}"
        assert r["max"]["mv"] <= MV_TOL, f"{name} a position MV is off"
        for field in ("class_w", "port_w", "active_w"):
            assert r["max"][field] <= WEIGHT_TOL, f"{name} {field} off"
        assert not r["mismatches"], f"{name} mismatches: {r['mismatches']}"


def test_db_frame():
    import sqlite3
    import pandas as pd
    from scripts.reconcile import _db_frame

    conn = sqlite3.connect(":memory:")

    conn.execute("CREATE TABLE securities (ticker TEXT, sec_type TEXT)")
    conn.execute("CREATE TABLE holdings (ticker TEXT, fund TEXT, shares REAL, passive_weight REAL)")
    conn.execute("CREATE TABLE prices (ticker TEXT, source TEXT, date TEXT, close REAL)")

    conn.executemany("INSERT INTO securities VALUES (?, ?)", [
        ("CASH", "cash"),
        ("SPY", "etf"),
        ("AAPL", "stock"),
        ("MSFT", "stock"),
    ])
    conn.executemany("INSERT INTO holdings VALUES (?, ?, ?, ?)", [
        ("CASH", "FundA", 1000.0, 0.0),
        ("SPY", "FundA", 10.0, 0.0),
        ("AAPL", "FundA", 10.0, 0.10),
        ("MSFT", "FundA", 5.0, 0.20),
        ("CASH", "FundB", 500.0, 0.0), # Another fund to test filtering
    ])
    # xlsx_snapshot source and date ordering
    conn.executemany("INSERT INTO prices VALUES (?, ?, ?, ?)", [
        ("SPY", "xlsx_snapshot", "2023-01-01", 90.0),
        ("SPY", "xlsx_snapshot", "2023-01-02", 100.0), # Latest snapshot
        ("SPY", "other", "2023-01-03", 110.0), # Should be ignored due to source
        ("AAPL", "xlsx_snapshot", "2023-01-02", 150.0),
        ("MSFT", "xlsx_snapshot", "2023-01-02", 200.0),
        ("CASH", "xlsx_snapshot", "2023-01-02", 1.0),
    ])

    df = _db_frame(conn, "FundA")

    # Math expectation:
    # CASH: 1000 * 1.0 = 1000
    # SPY: 10 * 100.0 = 1000
    # AAPL: 10 * 150.0 = 1500
    # MSFT: 5 * 200.0 = 1000
    # Total MV: 4500
    # Cash: 1000
    # ETF (Index): 1000
    # Invested = Total - Cash = 3500
    # Active Sleeve = Total - Cash - Index = 2500

    assert df.attrs["total"] == 4500.0
    assert len(df) == 4 # FundB should be filtered out

    aapl = df[df["ticker"] == "AAPL"].iloc[0]
    assert aapl["mv"] == 1500.0
    assert aapl["class_w"] == 1500.0 / 2500.0
    assert aapl["port_w"] == 1500.0 / 3500.0
    assert aapl["active_w"] == (1500.0 / 3500.0) - 0.10

    msft = df[df["ticker"] == "MSFT"].iloc[0]
    assert msft["mv"] == 1000.0
    assert msft["class_w"] == 1000.0 / 2500.0
    assert msft["active_w"] == (1000.0 / 3500.0) - 0.20

    cash = df[df["ticker"] == "CASH"].iloc[0]
    assert pd.isna(cash["class_w"])
    assert pd.isna(cash["port_w"])
    assert pd.isna(cash["active_w"])

    spy = df[df["ticker"] == "SPY"].iloc[0]
    assert pd.isna(spy["class_w"])
    assert pd.isna(spy["port_w"])
    assert pd.isna(spy["active_w"])

    conn.close()

if __name__ == "__main__":
    test_import_reconciles_to_workbook()
    print("OK")
