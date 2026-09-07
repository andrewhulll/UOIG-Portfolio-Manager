"""SQLite schema and connection helpers for the UOIG portfolio store.

Tables
------
securities    Intrinsic, ticker-keyed reference data (name, sector, cap, type).
holdings      Current positions per fund (shares, cost basis, benchmark weight).
transactions  Trade ledger (buys/sells/dividends/fees) — populated going forward.
prices        Daily price history per ticker (cached from the data provider).
dividends     Dividend history per ticker.
benchmarks    Index level history (IWV, IWM, SPY, ...).
nav_history   Daily fund value and net external cash flow (for TWR).
import_meta   Key/value provenance for the last seed/import.
api_cache     Durable TTL cache for live yfinance / Kalshi lookups (shared, survives restarts).
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from src.model import db as _db
from src.model.submissions import SCHEMA as SUBMISSIONS_SCHEMA

SCHEMA = """
CREATE TABLE IF NOT EXISTS securities (
    ticker      TEXT PRIMARY KEY,
    name        TEXT,
    sector      TEXT,
    cap_class   TEXT,
    sec_type    TEXT CHECK (sec_type IN ('stock', 'etf', 'cash'))
);

CREATE TABLE IF NOT EXISTS holdings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    fund              TEXT NOT NULL,
    ticker            TEXT NOT NULL,
    shares            REAL,
    entry_price       REAL,   -- split-adjusted buy-in (cost basis); cash = 1.0
    entry_date        TEXT,   -- ISO date
    passive_weight    REAL,   -- weight in the fund's benchmark at entry
    bench_ticker      TEXT,   -- benchmark used for active weight / excess return
    bench_entry_price REAL,   -- benchmark ETF price on the entry date
    UNIQUE (fund, ticker),
    FOREIGN KEY (ticker) REFERENCES securities (ticker)
);

CREATE TABLE IF NOT EXISTS transactions (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    date    TEXT NOT NULL,
    fund    TEXT NOT NULL,
    ticker  TEXT NOT NULL,
    action  TEXT CHECK (action IN ('buy', 'sell', 'div', 'fee')),
    shares  REAL,
    price   REAL,
    amount  REAL,
    note    TEXT
);

CREATE TABLE IF NOT EXISTS prices (
    ticker     TEXT NOT NULL,
    date       TEXT NOT NULL,
    close      REAL,
    adj_close  REAL,
    source     TEXT,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS dividends (
    ticker  TEXT NOT NULL,
    ex_date TEXT NOT NULL,
    amount  REAL,
    PRIMARY KEY (ticker, ex_date)
);

CREATE TABLE IF NOT EXISTS benchmarks (
    index_ticker TEXT NOT NULL,
    date         TEXT NOT NULL,
    close        REAL,
    PRIMARY KEY (index_ticker, date)
);

CREATE TABLE IF NOT EXISTS nav_history (
    fund        TEXT NOT NULL,
    date        TEXT NOT NULL,
    total_value REAL,
    net_flow    REAL,
    PRIMARY KEY (fund, date)
);

CREATE TABLE IF NOT EXISTS import_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker       TEXT PRIMARY KEY,
    gics_sector  TEXT,
    pe           REAL,   -- forward P/E (falls back to trailing)
    pb           REAL,   -- price / book
    ev_ebitda    REAL,   -- enterprise value / EBITDA
    market_cap   REAL,   -- USD
    week52_low   REAL,
    week52_high  REAL,
    description  TEXT,
    updated      TEXT,
    FOREIGN KEY (ticker) REFERENCES securities (ticker)
);

CREATE TABLE IF NOT EXISTS benchmark_holdings (
    index_ticker TEXT,    -- the benchmark ETF (IWV, IWM, ...)
    ticker       TEXT,    -- a constituent's ticker
    weight       REAL,    -- constituent weight in the index (fraction, 0-1)
    sector       TEXT,    -- raw GICS sector from the provider (uppercase)
    updated      TEXT,
    PRIMARY KEY (index_ticker, ticker)
);

CREATE TABLE IF NOT EXISTS benchmark_sectors (
    index_ticker TEXT,    -- the benchmark ETF (IWV, IWM, ...)
    sector       TEXT,    -- raw GICS sector name from the provider (uppercase)
    weight       REAL,    -- sector weight in the index (fraction, 0-1)
    updated      TEXT,
    PRIMARY KEY (index_ticker, sector)
);

CREATE TABLE IF NOT EXISTS api_cache (
    namespace   TEXT NOT NULL,     -- cache bucket: quote, series, holders, search, research, predictions
    key         TEXT NOT NULL,     -- ticker or composite key within the namespace
    payload     TEXT NOT NULL,     -- JSON-encoded cached value
    fetched_at  TEXT NOT NULL,     -- ISO-8601 UTC timestamp of the fetch
    ttl         INTEGER NOT NULL,  -- seconds this entry stays fresh
    PRIMARY KEY (namespace, key)
);
"""

SCHEMA += SUBMISSIONS_SCHEMA

# Weekly analyst work survives market-data reseeding.
_TABLES = [
    "api_cache",
    "import_meta", "fundamentals", "benchmark_holdings", "benchmark_sectors",
    "nav_history", "benchmarks", "dividends",
    "prices", "transactions", "holdings", "securities",
]


def get_connection(db: str | Path | None = None):
    """A DB connection. Postgres when DATABASE_URL / supabase.url.txt is set
    (the `db` path is ignored), otherwise the local SQLite file."""
    if _db.use_postgres():
        return _db.connect_pg()
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn) -> None:
    if _db.is_pg(conn):
        # Postgres has no executescript and no AUTOINCREMENT — run each statement
        # and map SQLite's autoincrement PK to an identity column.
        ddl = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                             "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY")
        ddl = re.sub(r"--[^\n]*", "", ddl)  # strip -- comments (some contain ';')
        cur = conn.cursor()
        try:
            for stmt in (s.strip() for s in ddl.split(";")):
                if stmt:
                    cur.execute(stmt)
        finally:
            cur.close()
        conn.commit()
        _migrate(conn)
        return
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)


# Columns added after the initial schema shipped. CREATE TABLE IF NOT EXISTS
# leaves existing tables untouched, so add any missing columns idempotently.
_ADDED_COLUMNS = [("fundamentals", "ev_ebitda", "REAL")]


def _migrate(conn) -> None:
    pg = _db.is_pg(conn)
    cur = conn.cursor()
    try:
        for table, col, typ in _ADDED_COLUMNS:
            qt = _db.quote_ident(table)
            qc = _db.quote_ident(col)
            if pg:
                cur.execute(f"ALTER TABLE {qt} ADD COLUMN IF NOT EXISTS {qc} {typ}")
            else:
                # PRAGMA table_info's argument can be passed as a parameterized value on SQLite
                # but `cur.execute("PRAGMA table_info(?)", (table,))` does not work in some versions,
                # so we can quote it properly or use pragma_table_info function:
                # `cur.execute("SELECT name FROM pragma_table_info(?)", (table,))`
                have = {r[0] for r in cur.execute("SELECT name FROM pragma_table_info(?)", (table,))}
                if col not in have:
                    cur.execute(f"ALTER TABLE {qt} ADD COLUMN {qc} {typ}")
    finally:
        cur.close()
    conn.commit()


def truncate_all(conn) -> None:
    """Clear all rows for an idempotent reseed (schema preserved). `_TABLES` is
    ordered children-first so FK constraints are satisfied on both backends."""
    cur = conn.cursor()
    try:
        for table in _TABLES:
            cur.execute(f"DELETE FROM {_db.quote_ident(table)}")
    finally:
        cur.close()
    conn.commit()
