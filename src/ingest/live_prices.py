"""Live latest-quote poller for held tickers.

Everything else in the system is pulled nightly (price *history*, dividends,
fundamentals, holders). The single number that needs to be fresh during the
session is the *current* price, so this module keeps a small in-process cache of
the latest quote per held ticker and refreshes it on a background thread every
~``interval`` seconds while the US market is open.

The cache is consumed by ``src.analytics.pnl._latest_two``: when a fresh quote
exists it overrides that ticker's spot price + previous close, so market value,
day change, weights and fund AUM all reflect the live price. Quotes older than
``_STALE`` (e.g. the poller died, or the market is closed) are ignored, so the
view falls back to the nightly DB close — never to a stale intraday number.

yfinance's freshest data is Yahoo's quote feed (``fast_info``), which is ~15 min
delayed for most US equities; polling faster than ~once a minute gains nothing
and risks rate-limiting, so the default cadence is 45s.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import yfinance as yf

from src.ingest.providers import _is_auth_error, reset_yf_auth, to_yf

log = logging.getLogger("uoig.live_prices")

# ticker -> {"price": float, "prev_close": float, "ts": float (epoch seconds)}
_LIVE: dict[str, dict] = {}
_LOCK = threading.Lock()
_STALE = 180.0          # quotes older than this are not used as overrides
_MAX_WORKERS = 8        # concurrent fast_info fetches per poll

_thread: threading.Thread | None = None
_stop = threading.Event()


def _num(v):
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def market_open(ts: pd.Timestamp | None = None) -> bool:
    """True during the NYSE regular session (Mon–Fri 9:30 AM–4:00 PM ET).

    Holidays are not accounted for — on a holiday the poller just fetches quotes
    that don't move, which is harmless. Uses pandas for tz handling (no tzdata
    dependency needed)."""
    now = ts or pd.Timestamp.now(tz="America/New_York")
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= mins < 16 * 60


def poll_once(tickers: list[str]) -> int:
    """Refresh the cache for ``tickers``. Returns how many quotes updated."""
    def _fetch(ticker: str) -> tuple[float, float] | None:
        """(last_price, previous_close) from Yahoo's quote feed, or None on failure."""
        try:
            fi = yf.Ticker(to_yf(ticker)).fast_info
            # Attribute access applies fast_info's snake_case aliasing; .get() does
            # not (its keys are camelCase: lastPrice/previousClose), so use attrs.
            px = _num(fi.last_price)
            prev = _num(fi.previous_close)
        except Exception as exc:  # noqa: BLE001 — best-effort; keep the prior cached quote
            log.warning("live quote fetch failed for %s: %s", ticker, exc, extra={"ticker": ticker})
            if _is_auth_error(exc):
                # Every ticker in this poll shares yfinance's cached crumb, so once
                # it's stuck all 8 workers fail identically forever until cleared —
                # reset it once so the next poll cycle (45s) re-negotiates.
                reset_yf_auth()
            return None
        if px is None or prev is None or prev == 0:
            return None
        return px, prev

    tickers = [t for t in dict.fromkeys(tickers) if t]
    if not tickers:
        return 0
    now = time.time()
    updated = 0
    workers = min(_MAX_WORKERS, len(tickers))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for t, res in zip(tickers, ex.map(_fetch, tickers)):
            if res is None:
                continue
            px, prev = res
            with _LOCK:
                _LIVE[t.upper()] = {"price": px, "prev_close": prev, "ts": now}
            updated += 1
    if updated < len(tickers):
        log.warning("live quote poll degraded: %d/%d tickers updated", updated, len(tickers))
    return updated


def overrides() -> dict[str, dict]:
    """Fresh {ticker: {price, prev_close}} quotes (newer than ``_STALE``).

    Stale entries are dropped so callers fall back to the nightly DB close."""
    cutoff = time.time() - _STALE
    with _LOCK:
        return {t: {"price": q["price"], "prev_close": q["prev_close"]}
                for t, q in _LIVE.items() if q["ts"] >= cutoff}


def start(get_tickers, interval: float = 45.0, idle_interval: float = 300.0) -> None:
    """Start the background poller once (idempotent).

    ``get_tickers`` is called each cycle to get the current held universe, so new
    holdings are picked up without a restart."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()

    def _loop() -> None:
        while not _stop.is_set():
            wait = idle_interval
            if market_open():
                try:
                    poll_once(get_tickers())
                    wait = interval
                except Exception:  # noqa: BLE001 — never let the poller thread die
                    log.exception("live-price poll cycle failed")
                    wait = interval
            _stop.wait(wait)

    _thread = threading.Thread(
        target=_loop,
        name="live-prices", daemon=True)
    _thread.start()


def stop() -> None:
    """Signal the poller to stop (used in tests / shutdown)."""
    _stop.set()
