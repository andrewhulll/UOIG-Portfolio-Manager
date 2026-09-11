"""Nightly last-known-good stock-tab snapshots for current holdings."""
from __future__ import annotations

import logging
import time

from src.config import db_path
from src.ingest.lookup import institutional_holders
from src.ingest.research import refresh_closed_snapshot
from src.ingest.universe import owned_tickers
from src.model import schema

log = logging.getLogger("uoig.snapshots")

_SNAPSHOT_TTL = 2592000  # 30 days; stale reads survive missed refreshes


def refresh_owned_snapshots(cfg: dict, conn=None) -> dict:
    """Refresh slow-changing stock tabs once for each current holding."""
    own = conn is None
    if own:
        conn = schema.get_connection(db_path(cfg))
    schema.create_schema(conn)
    tickers = owned_tickers(conn)
    if own:
        conn.close()

    summary = {"tickers": len(tickers), "research": 0, "holders": 0, "failed": []}
    pause = float((cfg.get("market_data") or {}).get("request_pause_seconds", 0))
    for index, ticker in enumerate(tickers):
        if index and pause > 0:
            time.sleep(pause)
        failures = []
        try:
            payload = refresh_closed_snapshot(ticker)
            if any(payload.get(k) for k in ("financials", "earnings", "research")):
                summary["research"] += 1
            else:
                failures.append("research-empty")
        except Exception as exc:  # noqa: BLE001 — preserve other tickers/sections
            failures.append(f"research:{exc}")
        try:
            institutional_holders(ticker, force=True, ttl=_SNAPSHOT_TTL)
            summary["holders"] += 1
        except Exception as exc:  # noqa: BLE001
            failures.append(f"holders:{exc}")
        if failures:
            summary["failed"].append(f"{ticker} ({'; '.join(failures)})")

    if summary["failed"]:
        log.warning("owned snapshot refresh degraded: %s", summary["failed"])
    return summary
