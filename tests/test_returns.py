"""Phase 2: holding-period return math — hermetic (no network)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.model import db as _db  # noqa: E402
_db.database_url = lambda: None  # hermetic: always use the throwaway SQLite file

from src.analytics.pnl import load_positions  # noqa: E402
from src.analytics.returns import enrich_returns  # noqa: E402
from src.config import load_config  # noqa: E402
from src.io.import_xlsx import import_workbook  # noqa: E402
from src.model.schema import get_connection  # noqa: E402


def _seed(tmp):
    cfg = load_config()
    cfg["database"] = str(Path(tmp) / "t.db")
    import_workbook(cfg)
    conn = get_connection(cfg["database"])
    # AAPL up 50% over the window; its benchmark (IWV) up 20% -> excess 30%
    rows = [("AAPL", "2022-01-27", 100.0), ("AAPL", "2026-06-25", 150.0),
            ("IWV", "2022-01-27", 100.0), ("IWV", "2026-06-25", 120.0)]
    conn.executemany(
        "INSERT OR REPLACE INTO prices (ticker, date, close, adj_close, source)"
        " VALUES (?, ?, ?, ?, 'yfinance')",
        [(t, d, p, p) for t, d, p in rows])
    conn.commit()
    return cfg, conn


def test_holding_period_returns():
    with tempfile.TemporaryDirectory() as tmp:
        cfg, conn = _seed(tmp)
        enr = enrich_returns(load_positions(cfg, conn), conn)
        conn.close()

    a = enr[(enr.fund == "Tall Firs") & (enr.ticker == "AAPL")].iloc[0]
    assert abs(a.hp_tr - 0.5) < 1e-9
    assert abs(a.bench_tr - 0.2) < 1e-9
    assert abs(a.excess_tr - 0.3) < 1e-9
    assert a.days_held > 0 and a.ann_tr > 0
    # index overlay & cash carry no holding-period return
    assert enr[enr.sec_type != "stock"].hp_tr.isna().all()


if __name__ == "__main__":
    test_holding_period_returns()
    print("OK")
