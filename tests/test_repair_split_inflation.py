import sqlite3

from scripts import repair_split_inflation as repair
from src.model import schema


def _db():
    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.execute("INSERT INTO securities (ticker, name, sec_type) VALUES ('GOOGL', 'Alphabet', 'stock')")
    conn.execute(
        "INSERT INTO holdings (fund, ticker, shares, entry_price) VALUES ('Tall Firs', 'GOOGL', 200, 5)"
    )
    conn.commit()
    return conn


def test_repair_is_guarded_dry_run_and_idempotent(monkeypatch):
    monkeypatch.setattr(repair, "_baseline_positions", lambda _cfg: {
        ("tall firs", "GOOGL"): {"shares": 10.0, "entry_price": 100.0}
    })
    conn = _db()

    preview = repair.repair_split_inflation({}, conn)
    assert preview["status"] == "dry-run"
    assert preview["repaired"][0]["splitRatio"] == 20
    assert conn.execute("SELECT shares, entry_price FROM holdings").fetchone() == (200.0, 5.0)

    result = repair.repair_split_inflation({}, conn, apply=True)
    assert result["status"] == "applied"
    assert conn.execute("SELECT shares, entry_price FROM holdings").fetchone() == (10.0, 100.0)

    again = repair.repair_split_inflation({}, conn, apply=True)
    assert again == {"status": "already-applied", "repaired": []}


def test_repair_ignores_an_ordinary_position_change(monkeypatch):
    monkeypatch.setattr(repair, "_baseline_positions", lambda _cfg: {
        ("tall firs", "GOOGL"): {"shares": 10.0, "entry_price": 100.0}
    })
    conn = _db()
    conn.execute("UPDATE holdings SET entry_price = 6 WHERE ticker = 'GOOGL'")

    result = repair.repair_split_inflation({}, conn, apply=True)

    assert result["repaired"] == []
    assert conn.execute("SELECT shares, entry_price FROM holdings").fetchone() == (200.0, 6.0)


def test_repair_v2_catches_rounded_google_split_after_v1_marker(monkeypatch):
    monkeypatch.setattr(repair, "_baseline_positions", lambda _cfg: {
        ("tall firs", "GOOGL"): {"shares": 586.2232, "entry_price": 119.64}
    })
    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.execute("INSERT INTO securities (ticker, name, sec_type) VALUES ('GOOGL', 'Alphabet', 'stock')")
    conn.execute(
        "INSERT INTO holdings (fund, ticker, shares, entry_price) "
        "VALUES (' Tall Firs ', 'GOOGL', 11724.46, 5.98)"
    )
    conn.execute(
        "INSERT INTO import_meta (key, value) VALUES ('repair_split_inflation_v1', '{}')"
    )
    conn.execute(
        "INSERT INTO import_meta (key, value) VALUES "
        "('repair_split_inflation_v2', '{\"positions\":[{\"fund\":\"tall firs\",\"ticker\":\"AVGO\"}]}')"
    )
    conn.commit()

    result = repair.repair_split_inflation({}, conn, apply=True)

    assert result["status"] == "applied"
    assert result["repaired"][0]["ticker"] == "GOOGL"
    assert result["repaired"][0]["splitRatio"] == 20
    assert conn.execute("SELECT shares, entry_price FROM holdings").fetchone() == (586.2232, 119.64)
