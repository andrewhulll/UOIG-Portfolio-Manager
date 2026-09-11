"""Durable, dialect-agnostic API cache: (namespace, key) -> JSON payload + TTL.

Backs the in-memory caches in ``src/ingest/*`` with a row in the shared store
(SQLite locally, Supabase/Postgres in prod) so cached yfinance / Kalshi results
survive restarts and are shared across instances — cutting repeat calls and the
rate-limiting (HTTP 429) that follows.

yfinance stays the source of truth: this only stores what a fetch already
returned. Every operation **fails soft** — any DB error (or a non-serializable
value) is treated as a cache miss / skipped write, so a cache problem can never
break a request; the caller just falls through to a live fetch.

Usage (layered under a module's existing in-memory cache):

    from src.model import cache
    hit = cache.get("quote", ticker)
    if hit is not cache.MISS:
        return hit                      # may legitimately be None
    value = _fetch_live(...)
    cache.set("quote", ticker, value, ttl=300)
    return value
"""
from __future__ import annotations

import datetime as dt
import json

from src.config import db_path, load_config
from src.model import db as _db
from src.model.schema import get_connection

# Sentinel distinguishing "not cached / expired" from a cached ``None`` value
# (quote_overview caches None for non-equities, and that should count as a hit).
MISS = object()

_DDL = (
    "CREATE TABLE IF NOT EXISTS api_cache ("
    "namespace TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL, "
    "fetched_at TEXT NOT NULL, ttl INTEGER NOT NULL, "
    "PRIMARY KEY (namespace, key))"
)

_COLS = ["namespace", "key", "payload", "fetched_at", "ttl"]
_dbpath = None
_ensured = False


def _path():
    global _dbpath
    if _dbpath is None:
        _dbpath = db_path(load_config())
    return _dbpath


def _ensure(conn) -> None:
    # Self-bootstrap the table once per process so the cache works even where the
    # schema wasn't (re)created — local SQLite, or a store predating this table.
    global _ensured
    if _ensured:
        return
    conn.execute(_DDL)
    conn.commit()
    _ensured = True


def get(namespace: str, key: str):
    """Return ``(value, age_seconds)`` when a fresh row exists (value may be
    ``None``), else ``MISS``. The age lets callers seed their in-memory copy with
    the true remaining freshness instead of granting it a full new TTL. Never
    raises — any failure is treated as a miss."""
    try:
        conn = get_connection(_path())
    except Exception:  # noqa: BLE001 — cache never breaks the caller
        return MISS
    try:
        _ensure(conn)
        row = conn.execute(
            _db.q(conn, "SELECT payload, fetched_at, ttl FROM api_cache "
                        "WHERE namespace = ? AND key = ?"),
            (namespace, key),
        ).fetchone()
        if not row:
            return MISS
        payload, fetched_at, ttl = row[0], row[1], row[2]
        age = (dt.datetime.now(dt.timezone.utc)
               - dt.datetime.fromisoformat(fetched_at)).total_seconds()
        if age > float(ttl):
            return MISS
        return json.loads(payload), age
    except Exception:  # noqa: BLE001
        return MISS
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def peek(namespace: str, key: str):
    """Return ``(value, age_seconds)`` even when a row's TTL has expired.

    Nightly-owned snapshots are last-known-good data rather than ordinary API
    cache entries: if tonight's upstream refresh fails, the application should
    keep serving yesterday's snapshot instead of falling through to a live
    request.  ``peek`` supports that read path while ``get`` retains normal TTL
    semantics for on-demand lookups and news.
    """
    try:
        conn = get_connection(_path())
    except Exception:  # noqa: BLE001
        return MISS
    try:
        _ensure(conn)
        row = conn.execute(
            _db.q(conn, "SELECT payload, fetched_at FROM api_cache "
                        "WHERE namespace = ? AND key = ?"),
            (namespace, key),
        ).fetchone()
        if not row:
            return MISS
        age = (dt.datetime.now(dt.timezone.utc)
               - dt.datetime.fromisoformat(row[1])).total_seconds()
        return json.loads(row[0]), age
    except Exception:  # noqa: BLE001
        return MISS
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def set(namespace: str, key: str, value, ttl: int) -> None:
    """Upsert a cache row. Never raises — a non-serializable value or a DB error
    just skips the write (the caller keeps the live result + its memory cache)."""
    try:
        payload = json.dumps(value)
    except (TypeError, ValueError):
        return
    try:
        conn = get_connection(_path())
    except Exception:  # noqa: BLE001
        return
    try:
        _ensure(conn)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        _db.executemany(
            conn, _db.upsert_sql(conn, "api_cache", _COLS, ["namespace", "key"]),
            [(namespace, key, payload, now, int(ttl))],
        )
        conn.commit()
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def purge_expired(horizon_seconds: int = 0) -> int:
    """Delete rows after their own TTL plus an optional retention horizon.

    The previous implementation used one fixed one-hour cutoff, which could
    remove a valid entry whose TTL was longer than an hour.  Evaluating each
    row's stored TTL keeps cleanup correct for both ten-minute News entries and
    multi-day last-known-good snapshots, without database-specific date SQL.
    Returns rows deleted; never raises.
    """
    try:
        conn = get_connection(_path())
    except Exception:  # noqa: BLE001
        return 0
    try:
        _ensure(conn)
        now = dt.datetime.now(dt.timezone.utc)
        rows = conn.execute(
            "SELECT namespace, key, fetched_at, ttl FROM api_cache"
        ).fetchall()
        expired = []
        for namespace, key, fetched_at, ttl in rows:
            try:
                age = (now - dt.datetime.fromisoformat(fetched_at)).total_seconds()
                if age > float(ttl) + max(0, int(horizon_seconds)):
                    expired.append((namespace, key))
            except (TypeError, ValueError):
                expired.append((namespace, key))
        if expired:
            _db.executemany(
                conn,
                "DELETE FROM api_cache WHERE namespace = ? AND key = ?",
                expired,
            )
        conn.commit()
        return len(expired)
    except Exception:  # noqa: BLE001
        return 0
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
