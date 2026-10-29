"""My Coverage companion routes: portfolio movers and member-owned watchlists."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import calendar
import re
import time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.analytics.coverage import FUNDS, context, movers, fundamental_rows, number, position_facts
from src.analytics.series import price_frame
from src.ingest.lookup import quote_overview, search_symbols
from src.ingest.providers import MarketDataRateLimited, MarketDataUnavailable, to_yf
from src.ingest.research import closed_snapshot
from src.model import db, schema

router = APIRouter(prefix="/api")


def identity(request: Request):
    from api.main import _current_user_id
    uid = _current_user_id(request)
    if not uid:
        raise HTTPException(401, "not authenticated")
    return uid


def connection():
    from api.main import _conn
    conn = _conn()
    try:
        schema.create_schema(conn)
        return conn
    except Exception:
        conn.close()
        raise


def canonical(ticker):
    value = to_yf(ticker.strip().upper())
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9^=-]{0,23}", value):
        raise HTTPException(422, "Enter a valid equity ticker.")
    return value


def owned_symbols(conn):
    rows = conn.execute("SELECT DISTINCT h.ticker FROM holdings h JOIN securities s ON s.ticker=h.ticker "
                        "WHERE h.shares > 0 AND s.sec_type='stock'").fetchall()
    return {to_yf(r[0].upper()): r[0] for r in rows}


def watch_quote(ticker, conn, owned=None, facts=None, prices=None):
    owned = owned if owned is not None else owned_symbols(conn)
    stored = owned.get(ticker)
    if stored:
        facts = facts if facts is not None else fundamental_rows(conn)
        prices = prices if prices is not None else price_frame(conn)
        f = facts.get(stored, {})
        series = prices[prices.ticker == stored]
        px = number(series.close.iloc[-1]) if len(series) else None
        prev = number(series.close.iloc[-2]) if len(series) > 1 else None
        name = conn.execute(db.q(conn, "SELECT name FROM securities WHERE ticker=?"), (stored,)).fetchone()[0]
        earnings = (closed_snapshot(stored).get("earnings") or {})
        q = {"n": name, "px": px, "chg": (px / prev - 1) * 100 if px is not None and prev else None,
             "mc": number(f.get("market_cap")), "lo": number(f.get("week52_low")), "hi": number(f.get("week52_high")),
             "forwardPE": number(f.get("forward_pe")), "volume": number(f.get("volume")),
             "averageVolume": number(f.get("average_volume")), "nextEarnings": earnings.get("next"),
             "nextEarningsEstimated": bool(earnings.get("nextEstimated")),
             "asOf": series.date.iloc[-1].date().isoformat() if len(series) else None}
    else:
        q = quote_overview(ticker, strict=True)
        if q is None:
            raise HTTPException(404, "No equity quote is available for this symbol.")
        q = {**q, "mc": q.get("mc") * 1e9 if q.get("mc") is not None else None}
    px, lo, hi = number(q.get("px")), number(q.get("lo")), number(q.get("hi"))
    vol, avg = number(q.get("volume")), number(q.get("averageVolume"))
    return {"ticker": ticker, "name": q.get("n") or ticker, "price": px,
            "dayChangePct": number(q.get("chg")), "marketCap": number(q.get("mc")),
            "rangePct": (px - lo) / (hi - lo) * 100 if px is not None and lo is not None and hi is not None and hi > lo else None,
            "volumeRatio": vol / avg if vol is not None and vol >= 0 and avg is not None and avg > 0 else None,
            "forwardPE": number(q.get("forwardPE")), "nextEarnings": q.get("nextEarnings"),
            "nextEarningsEstimated": bool(q.get("nextEarningsEstimated")), "asOf": q.get("asOf"),
            "factsAsOf": f.get("updated") if stored else q.get("asOf"),
            "held": bool(stored), "error": "Awaiting the nightly price refresh." if stored and px is None else None}


def safe_quote(ticker, conn, **kwargs):
    try:
        return watch_quote(ticker, conn, **kwargs)
    except MarketDataRateLimited:
        error = "Quote rate limited. Try again later."
    except Exception:
        error = "Quote unavailable. Your ticker is still saved."
    return {"ticker": ticker, "name": ticker, "error": error, "asOf": None}


@router.get("/movers")
def get_movers(fund: str = "all", window: str = "MTD", uid=Depends(identity)):
    from api.main import CFG
    conn = connection()
    try:
        try:
            return movers(CFG, conn, fund, window)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    finally:
        conn.close()


def _roll_forward(when, today):
    """`when` plus whole quarters until it is no longer in the past."""
    while when < today:
        year, month = divmod(when.year * 12 + when.month - 1 + 3, 12)
        day = min(when.day, calendar.monthrange(year, month + 1)[1])
        when = date(year, month + 1, day)
    return when


_NEXT_REPORT = {}
_NEXT_REPORT_TTL = 600  # report dates barely move; the nightly refresh rewrites them


def _next_report(ticker):
    hit = _NEXT_REPORT.get(ticker)
    if hit and time.time() - hit[0] < _NEXT_REPORT_TTL:
        return hit[1]
    try:
        value = closed_snapshot(ticker).get("earnings") or {}
    except Exception:
        return {}
    _NEXT_REPORT[ticker] = (time.time(), value)
    return value


def _today():
    """Today's date for the team. The server runs in UTC, which turns over at
    5pm Pacific and would treat that evening's reports as already past."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def _parse_day(text):
    try:
        return datetime.strptime((text or "").replace("reported ", "", 1), "%b %d, %Y").date()
    except ValueError:
        return None


def _workday(when, today):
    """(date to show, real date if it moved). Weekend reports (Berkshire's
    Saturday release) sit on the next trading day, where the market reacts; a
    past one whose Monday hasn't come yet sits on the Friday before."""
    if when.weekday() < 5:
        return when, None
    monday = when + timedelta(days=7 - when.weekday())
    return (monday if monday <= today or when >= today else when - timedelta(days=when.weekday() - 4)), when


@router.get("/earnings-calendar")
def get_earnings_calendar(fund: str = "all", days: int = 60, past_days: int = 0, uid=Depends(identity)):
    """Earnings dates for held names, read from the nightly snapshots (no live
    Yahoo calls): upcoming reports over `days`, plus reports already made in
    the last `past_days`. Dates that are only projected from the reporting
    cadence are flagged so the UI can badge them."""
    if fund != "all" and fund not in FUNDS:
        raise HTTPException(422, "fund must be all, tallfirs, or alumni")
    from api.main import CFG
    days, past_days = max(1, min(days, 180)), max(0, min(past_days, 30))
    names = list(FUNDS.values()) if fund == "all" else [FUNDS[fund]]
    conn = connection()
    try:
        marks = ",".join("?" * len(names))
        rows = conn.execute(db.q(conn, "SELECT h.ticker, s.name, s.sector FROM holdings h JOIN securities s ON s.ticker=h.ticker "
                                       f"WHERE h.shares > 0 AND s.sec_type='stock' AND h.fund IN ({marks}) "
                                       "GROUP BY h.ticker, s.name, s.sector"), names).fetchall()
        try:
            ctx = context(CFG, conn, fund)
        except Exception:
            ctx = None
    finally:
        conn.close()
    today = _today()
    horizon, since = today + timedelta(days=days), today - timedelta(days=past_days)
    events = []
    # Each snapshot read is a round trip to the cache store (~0.1s on a remote
    # database), so fan them out rather than paying for 40 in sequence.
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(rows)))) as pool:
        snapshots = list(pool.map(lambda r: _next_report(r[0]), rows))
    for (ticker, name, sector), earnings in zip(rows, snapshots):
        weight = position_facts(ctx, ticker, sector)["weight"] if ctx else None

        def add(day, **extra):
            shown, real = _workday(day, today)
            if since <= shown <= horizon:
                events.append({"ticker": ticker, "name": name, "sector": sector, "weight": weight,
                               "date": shown.isoformat(), "reportDate": real.isoformat() if real else None,
                               "daysUntil": (shown - today).days, "past": shown < today,
                               "estimated": False, **extra})

        nxt, estimated = _parse_day(earnings.get("next")), bool(earnings.get("nextEstimated"))
        if nxt and nxt < today:
            # Yahoo keeps the date of the report that just happened until the
            # company announces the next one, so a past "next" date means the
            # name has reported. Project one quarter at a time and flag it.
            nxt, estimated = _roll_forward(nxt, today), True
        if nxt:
            add(nxt, estimated=estimated)
        last = _parse_day(earnings.get("when"))
        if past_days and last and last < today:
            add(last, epsActual=earnings.get("epsActual"), epsEst=earnings.get("epsEst"),
                surprise=earnings.get("beat"))
    events.sort(key=lambda e: (e["date"], -(e["weight"] or 0), e["ticker"]))
    return {"fund": fund, "days": days, "pastDays": past_days, "events": events, "heldCount": len(rows)}


@router.get("/watchlist")
def get_watchlist(uid=Depends(identity)):
    conn = connection()
    try:
        tickers = [r[0] for r in conn.execute(db.q(conn, "SELECT ticker FROM watchlist WHERE user_id=? ORDER BY created_at,ticker"), (uid,)).fetchall()]
        owned, facts, prices = owned_symbols(conn), fundamental_rows(conn), price_frame(conn)
        # Stored positions are local DB reads. External quotes can involve network
        # I/O, so fetch those concurrently instead of making watchlist load time
        # grow linearly with every symbol.
        items = {
            ticker: safe_quote(ticker, conn, owned=owned, facts=facts, prices=prices)
            for ticker in tickers if ticker in owned
        }
        external = [ticker for ticker in tickers if ticker not in owned]
        if external:
            with ThreadPoolExecutor(max_workers=min(4, len(external))) as pool:
                quotes = pool.map(
                    lambda ticker: safe_quote(ticker, conn, owned=owned, facts=facts, prices=prices),
                    external,
                )
                items.update(zip(external, quotes))
        return {"items": [items[ticker] for ticker in tickers]}
    finally:
        conn.close()


class WatchlistBody(BaseModel):
    ticker: str = Field(min_length=1, max_length=24)


@router.post("/watchlist")
def add_watchlist(body: WatchlistBody, uid=Depends(identity)):
    ticker = canonical(body.ticker)
    conn = connection()
    try:
        existing = conn.execute(db.q(conn, "SELECT ticker FROM watchlist WHERE user_id=? AND ticker=?"), (uid, ticker)).fetchone()
        if existing:
            return safe_quote(ticker, conn)
        owned = owned_symbols(conn)
        if ticker in owned:
            item = safe_quote(ticker, conn, owned=owned)
        else:
            try:
                hits = search_symbols(ticker, limit=8, strict=True)
                if not any(to_yf(r["symbol"].upper()) == ticker for r in hits):
                    raise HTTPException(404, "No matching equity ticker was found.")
                # Search validates membership; a transient quote outage does not undo it.
                item = safe_quote(ticker, conn, owned=owned)
            except MarketDataRateLimited as exc:
                raise HTTPException(429, str(exc), headers={"Retry-After": "60"}) from exc
            except MarketDataUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(503, "Equity search is temporarily unavailable. Please try again.") from exc
        conn.execute(db.q(conn, "INSERT INTO watchlist (user_id,ticker,created_at) VALUES (?,?,?) "
                         "ON CONFLICT (user_id,ticker) DO NOTHING"), (uid, ticker, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return item
    finally:
        conn.close()


@router.delete("/watchlist/{ticker}")
def delete_watchlist(ticker: str, uid=Depends(identity)):
    ticker = canonical(ticker)
    conn = connection()
    try:
        conn.execute(db.q(conn, "DELETE FROM watchlist WHERE user_id=? AND ticker=?"), (uid, ticker))
        conn.commit()
        return {"ticker": ticker, "removed": True}
    finally:
        conn.close()
