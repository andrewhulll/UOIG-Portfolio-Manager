"""Kalshi prediction-market cards for the stock page's Predictions tab.

The curated map lives in PREDICTION_MARKETS.md (repo root): up to five Kalshi
markets per holding, edited by hand. This module parses that file, resolves each
mapped Kalshi ticker to its currently-open event, and shapes a Kalshi-style card
(title, category, top outcomes with implied probability + payout multiplier,
volume, market count). Market reads are public — no API key needed. Results are
cached in-process for a few minutes; the parsed map reloads when the file changes.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from pathlib import Path

import requests

from src.model import cache

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = dt.timezone.utc

BASE = "https://api.elections.kalshi.com/trade-api/v2"
_MAP_PATH = Path(__file__).resolve().parents[2] / "PREDICTION_MARKETS.md"
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 900
_map_cache: tuple[float, dict] | None = None


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _get(path: str, **params):
    r = requests.get(BASE + path, params=params, timeout=25)
    r.raise_for_status()
    return r.json()


# ---------- markdown map ----------
def load_market_map() -> dict[str, list[dict]]:
    """Parse PREDICTION_MARKETS.md -> {TICKER: [{label, kalshi, type, notes}]}.

    Re-reads only when the file's mtime changes.
    """
    global _map_cache
    try:
        mtime = _MAP_PATH.stat().st_mtime
    except FileNotFoundError:
        return {}
    if _map_cache and _map_cache[0] == mtime:
        return _map_cache[1]

    txt = _MAP_PATH.read_text(encoding="utf-8")
    out: dict[str, list[dict]] = {}
    for sec in re.finditer(r"^###\s+([A-Za-z0-9.\-]+)\b(.*?)(?=^###\s|\Z)", txt, re.S | re.M):
        ticker = sec.group(1).strip().upper()
        rows = []
        for line in sec.group(2).splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 3 or not cells[0].isdigit():
                continue
            kalshi = cells[2].strip().strip("`").strip().upper()
            if not kalshi:
                continue
            rows.append({"label": cells[1].strip(), "kalshi": kalshi,
                         "type": cells[3].strip() if len(cells) > 3 else "",
                         "notes": cells[4].strip() if len(cells) > 4 else ""})
        if rows:
            out[ticker] = rows
    _map_cache = (mtime, out)
    return out


# ---------- kalshi resolution ----------
def _mult(price: float) -> str | None:
    if price <= 0:
        return None
    m = 1.0 / price
    return (f"{m:.2f}x" if m < 10 else f"{m:.1f}x")


def _close_str(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(_ET)
        return d.strftime("%b %d @ ") + d.strftime("%I:%M%p").lstrip("0")
    except Exception:
        return ""


def _open_event(kalshi: str) -> dict | None:
    """Resolve a Kalshi ticker (series preferred) to its soonest-closing open event
    with nested markets. Falls back to treating the ticker as an event ticker."""
    try:
        evs = _get("/events", series_ticker=kalshi, status="open",
                   with_nested_markets="true", limit=100).get("events", [])
    except Exception:
        evs = []
    if not evs:
        try:
            e = _get(f"/events/{kalshi}", with_nested_markets="true").get("event")
            evs = [e] if e else []
        except Exception:
            evs = []
    evs = [e for e in evs if e and e.get("markets")]
    if not evs:
        return None

    def ekey(e):
        cs = [m.get("close_time") for m in e["markets"] if m.get("close_time")]
        return min(cs) if cs else "9999"

    return sorted(evs, key=ekey)[0]


def _card(entry: dict) -> dict | None:
    ev = _open_event(entry["kalshi"])
    if not ev:
        return None
    markets = ev.get("markets", [])

    def price(m):
        return _f(m.get("last_price_dollars")) or _f(m.get("yes_bid_dollars"))

    if len(markets) == 1:
        p = price(markets[0])
        outcomes = [{"label": "Yes", "pct": round(p * 100), "mult": _mult(p)},
                    {"label": "No", "pct": round((1 - p) * 100), "mult": _mult(1 - p)}]
    else:
        top = sorted(markets, key=lambda m: -price(m))[:2]
        outcomes = [{"label": m.get("yes_sub_title") or m.get("title") or "—",
                     "pct": round(price(m) * 100), "mult": _mult(price(m))} for m in top]

    closes = [m.get("close_time") for m in markets if m.get("close_time")]
    series = ev.get("series_ticker") or entry["kalshi"]
    return {
        "label": entry["label"],
        "title": ev.get("title") or entry["label"],
        "category": (ev.get("category") or entry.get("type") or "Markets") or "Markets",
        "closeStr": _close_str(min(closes) if closes else None),
        "outcomes": outcomes,
        "volume": int(sum(_f(m.get("volume_fp") or m.get("volume")) for m in markets)),
        "marketCount": len(markets),
        "series": series,
        "url": f"https://kalshi.com/markets/{str(series).lower()}",
    }


def stock_predictions(ticker: str) -> dict:
    ticker = ticker.upper()
    now = time.time()
    hit = _CACHE.get(ticker)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    cached = cache.get("predictions", ticker)
    if cached is not cache.MISS:
        _CACHE[ticker] = (now, cached)
        return cached

    entries = load_market_map().get(ticker, [])
    cards = []
    for e in entries:
        try:
            c = _card(e)
        except Exception:
            c = None
        if c:
            cards.append(c)
    payload = {"ticker": ticker, "cards": cards}
    _CACHE[ticker] = (now, payload)
    if cards:
        cache.set("predictions", ticker, payload, _TTL)
    return payload
