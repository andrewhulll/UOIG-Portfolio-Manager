"""Durable API cache (src/model/cache.py) — get/set/TTL/null-hit/age/purge/fail-soft.

Hermetic: forces SQLite (neutralizes both the DATABASE_URL env var AND the
supabase.url.txt fallback) and points the cache at throwaway temp files, so it
never touches the real store or a configured Supabase/Postgres.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.pop("DATABASE_URL", None)

from src.model import db as _db  # noqa: E402

# Force SQLite regardless of env var OR a repo-root supabase.url.txt — a test must
# never read/write a real Postgres/Supabase.
_db.database_url = lambda: None

from src.model import cache  # noqa: E402


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # let get_connection create it fresh
    cache._dbpath = path
    cache._ensured = False
    return path


def _val(hit):
    """Unwrap a (value, age) cache hit, asserting it wasn't a MISS."""
    assert hit is not cache.MISS
    value, age = hit
    assert age >= 0
    return value


def test_set_get_roundtrip():
    _fresh_db()
    cache.set("quote", "AAPL", {"px": 1.5, "n": None}, ttl=60)
    assert _val(cache.get("quote", "AAPL")) == {"px": 1.5, "n": None}


def test_get_returns_age():
    _fresh_db()
    cache.set("quote", "AGE", {"x": 1}, ttl=60)
    hit = cache.get("quote", "AGE")
    assert hit is not cache.MISS
    _value, age = hit
    assert 0 <= age < 5  # just written, so age is ~0


def test_missing_is_miss():
    _fresh_db()
    assert cache.get("quote", "NOPE") is cache.MISS


def test_cached_none_is_a_hit():
    # quote_overview caches None for non-equities — a cached None must read as a
    # hit, not a miss (otherwise we'd re-fetch every time).
    _fresh_db()
    cache.set("quote", "NA", None, ttl=60)
    assert _val(cache.get("quote", "NA")) is None


def test_expired_is_miss():
    _fresh_db()
    cache.set("quote", "OLD", {"x": 1}, ttl=0)
    time.sleep(0.02)
    assert cache.get("quote", "OLD") is cache.MISS


def test_upsert_replaces():
    _fresh_db()
    cache.set("series", "K", {"v": 1}, ttl=60)
    cache.set("series", "K", {"v": 2}, ttl=60)
    assert _val(cache.get("series", "K")) == {"v": 2}


def test_namespaces_are_isolated():
    _fresh_db()
    cache.set("quote", "X", {"a": 1}, ttl=60)
    assert cache.get("research", "X") is cache.MISS


def test_purge_expired_removes_rows():
    _fresh_db()
    cache.set("quote", "P", {"a": 1}, ttl=60)
    # horizon 0 => cutoff is "now", so the just-written (slightly earlier) row is
    # older than the cutoff and gets reclaimed.
    removed = cache.purge_expired(horizon_seconds=0)
    assert removed >= 1
    assert cache.get("quote", "P") is cache.MISS


def test_nonserializable_write_is_skipped():
    _fresh_db()
    cache.set("quote", "BAD", {"o": object()}, ttl=60)  # not JSON-serializable
    assert cache.get("quote", "BAD") is cache.MISS      # skipped, no exception


def test_circular_reference_write_is_skipped():
    _fresh_db()
    a = []
    a.append(a)
    cache.set("quote", "BAD_CIRC", a, ttl=60)  # circular reference, raises ValueError
    assert cache.get("quote", "BAD_CIRC") is cache.MISS # skipped, no exception


def test_fail_soft_on_unusable_db():
    # Parent is a file, so the SQLite path can't be created -> every op fails
    # soft: set is a no-op, get returns MISS, purge returns 0, nothing raises.
    fd, f = tempfile.mkstemp()
    os.close(fd)
    cache._dbpath = os.path.join(f, "cache.db")
    cache._ensured = False
    cache.set("quote", "Z", {"a": 1}, ttl=60)
    assert cache.get("quote", "Z") is cache.MISS
    assert cache.purge_expired() == 0


if __name__ == "__main__":
    test_set_get_roundtrip()
    test_get_returns_age()
    test_missing_is_miss()
    test_cached_none_is_a_hit()
    test_expired_is_miss()
    test_upsert_replaces()
    test_namespaces_are_isolated()
    test_purge_expired_removes_rows()
    test_nonserializable_write_is_skipped()
    test_circular_reference_write_is_skipped()
    test_fail_soft_on_unusable_db()
    print("OK")
