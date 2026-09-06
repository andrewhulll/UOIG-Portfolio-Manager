"""Populate the Capital IQ-backed ``daily_prices`` cache.

The job is incremental by ticker, idempotent on ``(ticker, date)``, and writes a
durable row to ``price_refresh_runs`` for every success, partial run, or failure.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
import uuid

from src.config import db_path
from src.ingest.capital_iq import get_provider
from src.model import db, schema


def _universe(conn: sqlite3.Connection, cfg: dict) -> tuple[list[str], set[str]]:
    """All non-cash holdings plus benchmark/risk series used by the dashboard."""
    held = [r[0] for r in conn.execute(
        "SELECT DISTINCT h.ticker FROM holdings h "
        "JOIN securities s ON s.ticker=h.ticker WHERE s.sec_type != 'cash'"
    )]
    bench = {f["benchmark"] for f in cfg["funds"]}
    risk = cfg.get("risk") or {}
    for key in (risk.get("market_proxy"), risk.get("risk_free")):
        if key:
            bench.add(key)
    sector_etfs = {ticker for sector in (cfg.get("sectors") or [])
                   for ticker in (sector.get("benchmarks") or [])}
    return sorted(set(held) | bench | sector_etfs), bench


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _number(value, integer: bool = False):
    if value is None:
        return None
    result = float(value)
    if math.isnan(result) or math.isinf(result):
        return None
    return int(result) if integer else result


def _finish_run(conn, run_id: str, status: str, summary: dict) -> None:
    error = json.dumps(summary.get("errors") or {}, sort_keys=True) or None
    conn.execute(db.q(conn,
        "UPDATE price_refresh_runs SET finished_at=?, status=?, tickers_succeeded=?, "
        "rows_upserted=?, error=? WHERE run_id=?"),
        (_now(), status, summary["succeeded"], summary["prices"], error, run_id))
    conn.commit()


def refresh(cfg: dict, history_years: float | None = None,
            full: bool = False, conn: sqlite3.Connection | None = None,
            provider=None) -> dict:
    own = conn is None
    if own:
        conn = schema.get_connection(db_path(cfg))
    schema.create_schema(conn)

    history_years = history_years or (cfg.get("market_data") or {}).get("history_years", 5)
    default_start = (dt.date.today() -
                     dt.timedelta(days=int(history_years * 365.25))).isoformat()
    tickers, bench_tickers = _universe(conn, cfg)
    run_id = uuid.uuid4().hex
    summary = {
        "run_id": run_id,
        "tickers": len(tickers),
        "succeeded": 0,
        "prices": 0,
        "dividends": 0,  # retained in the CLI contract; Layer 1 is prices only.
        "failed": [],
        "errors": {},
        "status": "running",
    }
    conn.execute(db.upsert_sql(conn, "price_refresh_runs",
        ["run_id", "started_at", "status", "tickers_total", "tickers_succeeded", "rows_upserted"],
        ["run_id"]), (run_id, _now(), "running", len(tickers), 0, 0))
    conn.commit()

    try:
        market = provider or get_provider(cfg)
        if provider is None:
            _ = market.client  # fail once, and log a job-level configuration error
        fetched_at = _now()
        for ticker in tickers:
            last = conn.execute(
                db.q(conn, "SELECT MAX(date) FROM daily_prices WHERE ticker=?"),
                (ticker,),
            ).fetchone()[0]
            start = default_start if (full or not last) else (
                dt.date.fromisoformat(str(last)) + dt.timedelta(days=1)).isoformat()
            try:
                frame = market.get_price_history([ticker], start=start)
                # No row is normal on weekends/holidays when this ticker already
                # has cache history. An empty initial/backfill response is a fault.
                if frame.empty:
                    if last and not full:
                        summary["succeeded"] += 1
                        continue
                    raise RuntimeError("Capital IQ returned no price rows")

                rows = []
                for row in frame.itertuples():
                    rows.append((
                        row.ticker, row.date,
                        _number(row.open),
                        _number(row.high),
                        _number(row.low),
                        float(row.close),
                        _number(row.volume, integer=True),
                        fetched_at,
                    ))
                db.executemany(conn, db.upsert_sql(conn, "daily_prices",
                    ["ticker", "date", "open", "high", "low", "close", "volume", "fetched_at"],
                    ["ticker", "date"]), rows)

                if ticker in bench_tickers:
                    db.executemany(conn, db.upsert_sql(conn, "benchmarks",
                        ["index_ticker", "date", "close"], ["index_ticker", "date"]),
                        [(row.ticker, row.date, float(row.close)) for row in frame.itertuples()])
                conn.commit()
                summary["prices"] += len(rows)
                summary["succeeded"] += 1
            except Exception as exc:  # one bad symbol must not discard the rest
                conn.rollback()
                summary["failed"].append(ticker)
                summary["errors"][ticker] = str(exc)

        summary["status"] = "success" if not summary["failed"] else "partial"
        conn.execute(db.upsert_sql(conn, "import_meta", ["key", "value"], ["key"]),
                     ("last_refresh", _now()))
        conn.commit()
        _finish_run(conn, run_id, summary["status"], summary)
        return summary
    except Exception as exc:
        conn.rollback()
        summary["status"] = "failed"
        summary["errors"]["job"] = str(exc)
        _finish_run(conn, run_id, "failed", summary)
        raise
    finally:
        if own:
            conn.close()
