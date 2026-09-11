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
import logging
import sqlite3
import time

from src.config import db_path
from src.ingest.providers import get_provider
from src.ingest.universe import owned_tickers
from src.model import db, schema

log = logging.getLogger("uoig.refresh")


def _universe(conn: sqlite3.Connection, cfg: dict) -> tuple[list[str], set[str]]:
    held = owned_tickers(conn)
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

    last_dates_raw = conn.execute(
        db.q(conn, "SELECT ticker, MAX(date) FROM prices WHERE source != 'xlsx_snapshot' GROUP BY ticker")
    ).fetchall()
    last_dates = {r[0]: r[1] for r in last_dates_raw}
    imported = conn.execute(
        db.q(conn, "SELECT value FROM import_meta WHERE key = ?"), ("import_date",)
    ).fetchone()
    # The workbook is a current-position snapshot: its shares and entry prices
    # are already adjusted for every split on or before the import date.  When
    # there is no downloaded history yet, use that date as the corporate-action
    # boundary instead of replaying years of old splits into current holdings.
    import_date = imported[0] if imported else None

    pause = float((cfg.get("market_data") or {}).get("request_pause_seconds", 0))
    for index, t in enumerate(tickers):
        if index and pause > 0:
            time.sleep(pause)
        last = last_dates.get(t)
        start = default_start if (full or not last) else max(
            default_start,
            (dt.date.fromisoformat(last) - dt.timedelta(days=400)).isoformat()
        )

        ph = provider.get_price_history([t], start=start)
        if ph.empty:
            summary["failed"].append(t)
            continue

        sp = provider.get_splits([t], start=start)
        if not sp.empty:
            for r in sp.itertuples():
                ratio = float(r.ratio)
                # The trailing history window intentionally overlaps prior
                # refreshes.  Only a split newer than the data boundary is new;
                # otherwise shares would be multiplied again on every refresh.
                split_boundary = max((d for d in (last, import_date) if d), default=None)
                if ratio > 0 and (split_boundary is None or r.date > split_boundary):
                    conn.execute(
                        db.q(conn, "UPDATE holdings SET shares = shares * ?, entry_price = entry_price / ? WHERE ticker = ? AND (entry_date IS NULL OR entry_date < ?)"),
                        (ratio, ratio, t, r.date)
                    )
                    if t in bench_tickers:
                        conn.execute(
                            db.q(conn, "UPDATE holdings SET bench_entry_price = bench_entry_price / ? WHERE bench_ticker = ? AND (entry_date IS NULL OR entry_date < ?)"),
                            (ratio, t, r.date)
                        )

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
    if summary["failed"]:
        log.warning("nightly refresh: %d/%d tickers returned no price history: %s",
                    len(summary["failed"]), summary["tickers"], summary["failed"],
                    extra={"failed_tickers": summary["failed"]})
    else:
        log.info("nightly refresh complete: %d tickers, %d prices, %d dividends",
                  summary["tickers"], summary["prices"], summary["dividends"])
    return summary
