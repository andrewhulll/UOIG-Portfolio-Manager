"""Pull market data into the store.

Incremental by default: each ticker is fetched only from the day after its last
stored (non-snapshot) price, so the nightly run is cheap. The first run (or
``full=True``) backfills ``history_years`` of daily prices + dividends, which
seeds the returns/risk analytics in later phases.

Cash sweeps are skipped (held at $1.00). The fund benchmarks plus the configured
market proxy / risk-free ticker are fetched too and mirrored into ``benchmarks``.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from src.config import db_path
from src.ingest.providers import get_provider
from src.model import db, schema


def _universe(conn: sqlite3.Connection, cfg: dict) -> tuple[list[str], set[str]]:
    held = [r[0] for r in conn.execute(
        "SELECT ticker FROM securities WHERE sec_type != 'cash'"
    )]
    bench = {f["benchmark"] for f in cfg["funds"]}
    risk = cfg.get("risk") or {}
    for k in (risk.get("market_proxy"), risk.get("risk_free")):
        if k:
            bench.add(k)
    # iShares sector ETFs the sector page charts against (config `sectors`).
    sector_etfs = {t for s in (cfg.get("sectors") or []) for t in (s.get("benchmarks") or [])}
    return sorted(set(held) | bench | sector_etfs), bench


def refresh(cfg: dict, history_years: float | None = None,
            full: bool = False, conn: sqlite3.Connection | None = None) -> dict:
    own = conn is None
    if own:
        conn = schema.get_connection(db_path(cfg))
    schema.create_schema(conn)

    history_years = history_years or (cfg.get("market_data") or {}).get("history_years", 5)
    default_start = (dt.date.today() - dt.timedelta(days=int(history_years * 365.25))).isoformat()
    provider = get_provider(cfg)
    tickers, bench_tickers = _universe(conn, cfg)

    summary = {"tickers": len(tickers), "prices": 0, "dividends": 0, "failed": []}
    for t in tickers:
        last = conn.execute(
            db.q(conn, "SELECT MAX(date) FROM prices WHERE ticker = ? AND source != 'xlsx_snapshot'"),
            (t,),
        ).fetchone()[0]
        start = default_start if (full or not last) else (
            dt.date.fromisoformat(last) + dt.timedelta(days=1)).isoformat()

        ph = provider.get_price_history([t], start=start)
        if ph.empty:
            summary["failed"].append(t)
            continue

        db.executemany(
            conn,
            db.upsert_sql(conn, "prices", ["ticker", "date", "close", "adj_close", "source"], ["ticker", "date"]),
            [(r.ticker, r.date, float(r.close), float(r.adj_close), "yfinance") for r in ph.itertuples()],
        )
        summary["prices"] += len(ph)

        if t in bench_tickers:
            db.executemany(
                conn,
                db.upsert_sql(conn, "benchmarks", ["index_ticker", "date", "close"], ["index_ticker", "date"]),
                [(r.ticker, r.date, float(r.close)) for r in ph.itertuples()],
            )

        dv = provider.get_dividends([t], start=start)
        if not dv.empty:
            db.executemany(
                conn,
                db.upsert_sql(conn, "dividends", ["ticker", "ex_date", "amount"], ["ticker", "ex_date"]),
                [(r.ticker, r.ex_date, float(r.amount)) for r in dv.itertuples()],
            )
            summary["dividends"] += len(dv)

    conn.execute(
        db.upsert_sql(conn, "import_meta", ["key", "value"], ["key"]),
        ("last_refresh", dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    if own:
        conn.close()
    return summary
