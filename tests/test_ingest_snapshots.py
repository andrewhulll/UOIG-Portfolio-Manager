import sqlite3

from src.ingest import snapshots
from src.model import schema


def test_refresh_owned_snapshots_only_visits_current_holdings(monkeypatch):
    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.executemany("INSERT INTO securities (ticker, sec_type) VALUES (?, ?)", [
        ("AAPL", "stock"), ("OLD", "stock"), ("CASH", "cash")])
    conn.executemany("INSERT INTO holdings (fund, ticker, shares) VALUES (?, ?, ?)", [
        ("Fund", "AAPL", 2), ("Fund", "OLD", 0), ("Fund", "CASH", 10)])
    seen = []
    monkeypatch.setattr(snapshots, "refresh_closed_snapshot", lambda t: (
        seen.append(("research", t)) or {"financials": {"rows": []}}))
    monkeypatch.setattr(snapshots, "institutional_holders", lambda t, **_kw: (
        seen.append(("holders", t)) or []))

    result = snapshots.refresh_owned_snapshots({}, conn=conn)
    assert result["tickers"] == 1
    assert seen == [("research", "AAPL"), ("holders", "AAPL")]
