"""Regression coverage for the merged workbook import cleanup and batching."""
import sqlite3

import openpyxl

from src.io import import_xlsx


def test_batched_import_preserves_shared_tickers_and_snapshots(monkeypatch, tmp_path):
    workbook = openpyxl.Workbook()
    first = workbook.active
    first.title = "First"
    second = workbook.create_sheet("Second")
    for sheet in (first, second):
        sheet.append(["header"])
    first.append(["Technology", "Large", "Apple", "AAPL", 2, 100, 200, 90])
    first.append(["Index", "Large", "S&P ETF", "SPY", 1, 400, 400, 380])
    second.append(["Other", "Large", "Apple", "AAPL", 3, 110, 330, 95])
    second.append(["Cash", "Cash", "Cash sweep", "BGNXX", None, None, 50])
    path = tmp_path / "holdings.xlsx"
    workbook.save(path)
    workbook.close()
    monkeypatch.setattr(import_xlsx, "workbook_path", lambda cfg: path)
    cfg = {"funds": [
        {"name": "First", "sheet": "First", "benchmark": "SPY"},
        {"name": "Second", "sheet": "Second", "benchmark": "SPY"},
    ]}
    conn = sqlite3.connect(":memory:")
    try:
        summary = import_xlsx.import_workbook(cfg, conn=conn)
        assert summary["funds"] == {"First": 2, "Second": 2}
        assert summary["n_securities"] == 3
        assert len(summary["warnings"]) == 1
        assert conn.execute("SELECT sector FROM securities WHERE ticker='AAPL'").fetchone() == ("Technology",)
        assert conn.execute("SELECT COUNT(*) FROM holdings").fetchone() == (4,)
        assert conn.execute("SELECT SUM(shares) FROM holdings WHERE ticker='AAPL'").fetchone() == (5,)
        assert conn.execute("SELECT close FROM prices WHERE ticker='AAPL'").fetchone() == (110,)
        assert conn.execute("SELECT close FROM benchmarks WHERE index_ticker='SPY'").fetchone() == (400,)
        assert conn.execute("SELECT shares, entry_price FROM holdings WHERE ticker='BGNXX'").fetchone() == (50, 1)
        assert conn.execute("SELECT value FROM import_meta WHERE key='n_securities'").fetchone() == ("3",)
        import_xlsx.import_workbook(cfg, conn=conn)
        assert conn.execute("SELECT COUNT(*) FROM holdings").fetchone() == (4,)
    finally:
        conn.close()
