"""Backend-agnostic DB helpers so the store runs on SQLite (local/dev/tests) or
Postgres/Supabase (hosted) with the same query code.

Backend selection: if a Postgres URL is configured (``DATABASE_URL`` env var, or a
git-ignored ``supabase.url.txt`` at the repo root), the app uses Postgres; otherwise
it falls back to the local SQLite file. The differences we paper over here are the
paramstyle (``?`` vs ``%s``), the upsert syntax (``INSERT OR REPLACE`` vs
``ON CONFLICT``), and ``executemany`` (a Connection method on sqlite3 but only a
Cursor method on psycopg). Rows are plain tuples on both backends (the codebase
reads by positional index), so no custom row factory is needed.
"""
from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def database_url() -> str | None:
    """Postgres URL from DATABASE_URL, else repo-root supabase.url.txt, else None."""
    env = os.environ.get("DATABASE_URL")
    if env and env.strip():
        return env.strip()
    try:
        for line in (_ROOT / "supabase.url.txt").read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                return s
    except FileNotFoundError:
        pass
    return None


def use_postgres() -> bool:
    # Explicit local/test override when a developer has a saved production URL but
    # needs the bundled SQLite database. Never enabled unless deliberately set.
    if os.environ.get("UOIG_FORCE_SQLITE", "").lower() in ("1", "true", "yes"):
        return False
    return bool(database_url())


def _parse_url(url: str) -> dict:
    """Split a postgres URL into psycopg connect() kwargs.

    We parse it ourselves (rather than hand the raw URL to libpq) so an
    un-encoded password — Supabase passwords often contain '@', '$', etc. — is
    passed verbatim instead of corrupting the host split. `rsplit('@', 1)` is
    safe because the host portion never contains '@'. Percent-escapes are decoded
    if present, so both raw and URL-encoded passwords work.
    """
    from urllib.parse import unquote
    rest = url.split("://", 1)[1]
    userinfo, hostpart = rest.rsplit("@", 1)
    user, _, pw = userinfo.partition(":")
    hostport, _, dbname = hostpart.partition("/")
    host, _, port = hostport.partition(":")
    dbname = dbname.split("?", 1)[0]
    out = {"host": host, "user": unquote(user), "password": unquote(pw),
           "dbname": dbname or "postgres", "sslmode": "require"}
    if port:
        out["port"] = int(port)
    return out


_pool = None
_pool_lock = None


class _PooledConn:
    """Thin proxy over a pooled psycopg connection. ``close()`` hands the
    connection back to the pool (rolling back anything uncommitted) instead of
    tearing down the TCP+TLS+auth session, so the many short
    ``get_connection()`` / ``conn.close()`` call sites reuse warm connections."""

    __slots__ = ("_conn", "_pool")

    def __init__(self, conn, pool):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_pool", pool)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._conn is not None:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        self.close()
        return False

    def close(self):
        conn = object.__getattribute__(self, "_conn")
        if conn is None:
            return
        object.__setattr__(self, "_conn", None)
        try:
            if not conn.closed:
                conn.rollback()
        finally:
            self._pool.putconn(conn)


def _get_pool(url: str | None):
    """Process-wide connection pool, or None when pooling is off/unavailable."""
    global _pool, _pool_lock
    if os.environ.get("UOIG_PG_POOL", "1").lower() in ("0", "false", "no"):
        return None
    try:
        from psycopg_pool import ConnectionPool
    except ImportError:
        return None
    import threading
    if _pool_lock is None:
        _pool_lock = threading.Lock()
    with _pool_lock:
        if _pool is None:
            max_size = int(os.environ.get("UOIG_PG_POOL_MAX", "10"))
            _pool = ConnectionPool(
                kwargs={**_parse_url(url or database_url()),
                        "prepare_threshold": None, "connect_timeout": 10},
                min_size=1, max_size=max_size,
                # Supabase/PgBouncer drop idle sessions; recycle before that and
                # verify on checkout so a dead socket never reaches a request.
                max_idle=240, max_lifetime=1800,
                check=ConnectionPool.check_connection,
                open=True, timeout=15,
            )
        return _pool


def connect_pg(url: str | None = None):
    """A psycopg (v3) connection. prepare_threshold=None keeps us compatible with
    Supabase's poolers (PgBouncer/Supavisor), which don't support prepared
    statements that outlive a transaction.

    Connections come from a process-wide pool (``psycopg_pool``) so each request
    skips the TCP+TLS+auth handshake to Supabase; ``close()`` returns them to the
    pool. Set ``UOIG_PG_POOL=0`` to open a fresh connection every time."""
    pool = _get_pool(url)
    if pool is not None:
        return _PooledConn(pool.getconn(), pool)
    import psycopg  # lazy import so SQLite-only environments don't need it
    # connect_timeout so a stalled Supabase/pooler fails fast (10s) instead of
    # hanging a request — matters most for the per-op cache connections.
    return psycopg.connect(**_parse_url(url or database_url()),
                           prepare_threshold=None, connect_timeout=10)


def is_pg(conn) -> bool:
    return isinstance(conn, _PooledConn) or type(conn).__module__.split(".", 1)[0] == "psycopg"


def q(conn, sql: str) -> str:
    """Translate ``?`` placeholders to ``%s`` on Postgres (no-op on SQLite).
    Safe here because none of our queries contain literal ``?`` or ``%``."""
    return sql.replace("?", "%s") if is_pg(conn) else sql


def quote_ident(name: str) -> str:
    """Safely quote an SQL identifier (table, column) to prevent injection."""
    return '"' + name.replace('"', '""') + '"'


def executemany(conn, sql: str, seq) -> None:
    """Uniform executemany — psycopg exposes it only on the cursor."""
    cur = conn.cursor()
    try:
        cur.executemany(q(conn, sql), list(seq))
    finally:
        cur.close()


def upsert_sql(conn, table: str, cols: list[str], conflict: list[str]) -> str:
    """An upsert-by-primary-key statement in the right dialect.
    SQLite: ``INSERT OR REPLACE``. Postgres: ``INSERT ... ON CONFLICT DO UPDATE``."""
    qt = quote_ident(table)
    qcols = [quote_ident(c) for c in cols]
    qconflict = [quote_ident(c) for c in conflict]

    collist = ", ".join(qcols)
    if is_pg(conn):
        marks = ", ".join(["%s"] * len(cols))
        updates = ", ".join(f"{qc}=EXCLUDED.{qc}" for c, qc in zip(cols, qcols) if c not in conflict)
        tail = (f" ON CONFLICT ({', '.join(qconflict)}) DO UPDATE SET {updates}"
                if updates else f" ON CONFLICT ({', '.join(qconflict)}) DO NOTHING")
        return f"INSERT INTO {qt} ({collist}) VALUES ({marks}){tail}"
    marks = ", ".join(["?"] * len(cols))
    return f"INSERT OR REPLACE INTO {qt} ({collist}) VALUES ({marks})"
