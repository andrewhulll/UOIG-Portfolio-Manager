"""On-demand per-stock research pull from yfinance for the stock-detail tabs.

Powers the Financials, Earnings, News and Research tabs of the terminal's stock
page. Each section is fetched live, normalized to display-ready JSON, and wrapped
in its own try/except so a partial failure (e.g. a name with no analyst coverage)
still returns the sections that did resolve. Results are cached in-process for a
few minutes so re-opening a ticker is instant.

Numbers are formatted to strings here (mirroring api/build.py); the frontend only
computes geometry (bar heights, consensus-bar widths) and colors.
"""
from __future__ import annotations

import datetime as dt
import math
import time

import pandas as pd

from src.ingest.providers import yf_ticker
from src.model import cache

_CACHE: dict[str, tuple[float, dict]] = {}       # unowned full-page bundles
_NEWS_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 900              # unowned page bundle: 15 minutes
_NEWS_TTL = 600         # news is the only short-lived owned-ticker data
_SNAPSHOT_TTL = 2592000  # 30-day cleanup grace; snapshot reads deliberately allow stale


# ---------- small formatters ----------
def _num(v):
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _money(v):
    """Raw USD -> compact string ($44.1B, $3.30T)."""
    f = _num(v)
    if f is None:
        return None
    a = abs(f)
    if a >= 1e12:
        return f"${f / 1e12:.2f}T"
    if a >= 1e9:
        return f"${f / 1e9:.1f}B"
    if a >= 1e6:
        return f"${f / 1e6:.1f}M"
    return f"${f:,.0f}"


def _pct(v, dp=0, signed=True):
    f = _num(v)
    if f is None:
        return None
    return f"{f:+.{dp}f}%" if signed else f"{f:.{dp}f}%"


def _qlabel(ts):
    d = pd.Timestamp(ts)
    return f"{((d.month - 1) // 3) + 1}Q{str(d.year)[2:]}"


def _row(df, *names):
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None


def _ago(ts, now):
    """ISO string or epoch seconds -> '2h ago'."""
    try:
        if ts is None:
            return ""
        if isinstance(ts, (int, float)):
            when = dt.datetime.fromtimestamp(float(ts), dt.timezone.utc)
        else:
            when = pd.Timestamp(ts).to_pydatetime()
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
        secs = (now - when).total_seconds()
        if secs < 3600:
            return f"{max(1, int(secs // 60))}m ago"
        if secs < 86400:
            return f"{int(secs // 3600)}h ago"
        return f"{int(secs // 86400)}d ago"
    except Exception:
        return ""


# ---------- sections ----------
def _financials(tk):
    inc = None
    try:
        inc = tk.quarterly_income_stmt
    except Exception:
        inc = None
    if inc is None or inc.empty:
        return None, None
    try:
        cf = tk.quarterly_cashflow
    except Exception:
        cf = None

    rev = _row(inc, "Total Revenue", "Operating Revenue")
    ni = _row(inc, "Net Income", "Net Income Common Stockholders")
    gp = _row(inc, "Gross Profit")
    oi = _row(inc, "Operating Income", "Total Operating Income As Reported")
    eps = _row(inc, "Diluted EPS", "Basic EPS")
    fcf = _row(cf, "Free Cash Flow")

    cols = list(inc.columns)            # newest..oldest
    latest = cols[0]
    yearago = cols[4] if len(cols) > 4 else None

    bars = []
    for c in reversed(cols[:5]):        # oldest..newest, last 5
        bars.append({
            "period": _qlabel(c),
            "revenue": (_num(rev[c]) / 1e9) if rev is not None and _num(rev[c]) is not None else None,
            "netIncome": (_num(ni[c]) / 1e9) if ni is not None and _num(ni[c]) is not None else None,
        })

    def yoy(series):
        if series is None or yearago is None:
            return None
        a, b = _num(series[latest]), _num(series[yearago])
        if a is None or not b:
            return None
        return (a - b) / abs(b) * 100

    def money_row(label, series):
        # "Prior" shows the year-ago quarter so the YoY delta reconciles with
        # the two displayed numbers (#29).
        if series is None:
            return None
        return {"label": label,
                "cur": _money(series[latest]) or "—",
                "prev": (_money(series[yearago]) if yearago is not None else None) or "—",
                "yoy": _pct(yoy(series), 0) or "—"}

    rows = []
    r = money_row("Revenue", rev)
    if r:
        rows.append(r)
    if gp is not None and rev is not None:
        gm = gp / rev * 100
        ppy = None
        if yearago is not None and _num(gm[latest]) is not None and _num(gm[yearago]) is not None:
            ppy = _num(gm[latest]) - _num(gm[yearago])
        rows.append({"label": "Gross margin",
                     "cur": f"{_num(gm[latest]):.1f}%" if _num(gm[latest]) is not None else "—",
                     "prev": f"{_num(gm[yearago]):.1f}%" if yearago is not None and _num(gm[yearago]) is not None else "—",
                     "yoy": (f"{ppy:+.1f}pp" if ppy is not None else "—")})
    for lbl, ser in [("Operating income", oi), ("Net income", ni), ("Free cash flow", fcf)]:
        r = money_row(lbl, ser)
        if r:
            rows.append(r)
    if eps is not None:
        a, b = _num(eps[latest]), (_num(eps[yearago]) if yearago is not None else None)
        rows.append({"label": "Diluted EPS",
                     "cur": f"${a:.2f}" if a is not None else "—",
                     "prev": f"${b:.2f}" if b is not None else "—",
                     "yoy": _pct(yoy(eps), 0) or "—"})

    rev_yoy = yoy(rev)
    margin = None
    if ni is not None and rev is not None and _num(rev[latest]):
        margin = _num(ni[latest]) / _num(rev[latest]) * 100
    cap_bits = []
    if rev_yoy is not None and _money(rev[latest]):
        cap_bits.append(f"Revenue {_pct(rev_yoy, 0)} YoY to {_money(rev[latest])}")
    if margin is not None:
        cap_bits.append(f"net margin {margin:.0f}%")
    # Full last-4-quarters income statement (line items x quarters) for the
    # statement-grid box on the Financials tab. Oldest..newest to match the bars.
    qcols = list(reversed(cols[:4]))
    # Money rows carry RAW dollars so the frontend can format each value
    # adaptively (B/M/K, the same _kd logic used elsewhere); EPS stays per-share.
    stmt_defs = [
        ("Revenue", "top", ("Total Revenue", "Operating Revenue")),
        ("Cost of revenue", "exp", ("Cost Of Revenue",)),
        ("Gross profit", "sub", ("Gross Profit",)),
        ("Operating expenses", "exp", ("Operating Expense",)),
        ("Operating income", "sub", ("Operating Income", "Total Operating Income As Reported")),
        ("Pretax income", "line", ("Pretax Income",)),
        ("Net income", "net", ("Net Income", "Net Income Common Stockholders")),
        ("Diluted EPS", "eps", ("Diluted EPS", "Basic EPS")),
    ]
    stmt_rows = []
    for label, kind, names in stmt_defs:
        ser = _row(inc, *names)
        if ser is None:
            continue
        vals = [_num(ser[c]) for c in qcols]
        if all(v is None for v in vals):
            continue
        prec = 2 if kind == "eps" else 0  # EPS to cents; dollars to whole dollars
        stmt_rows.append({"label": label, "kind": kind,
                          "vals": [round(v, prec) if v is not None else None for v in vals]})
    statement = {"quarters": [_qlabel(c) for c in qcols], "rows": stmt_rows} if stmt_rows else None

    financials = {"bars": bars, "rows": rows, "caption": " · ".join(cap_bits),
                  "statement": statement}

    # Reported EPS per quarter (newest..oldest, up to 4) from the income statement.
    # Lets _earnings degrade gracefully when tk.earnings_dates is unavailable —
    # common on datacenter IPs, where that Yahoo endpoint returns empty.
    eps_hist = []
    if eps is not None:
        for c in cols[:4]:
            a = _num(eps[c])
            if a is not None:
                eps_hist.append({"q": _qlabel(c), "ts": c, "act": f"{a:.2f}"})

    rev_summary = {
        "revActual": _money(rev[latest]) if rev is not None else None,
        "revYoY": _pct(rev_yoy, 0) if rev_yoy is not None else None,
        "epsHist": eps_hist,
    }
    return financials, rev_summary


def _earnings(tk, rev_summary):
    try:
        ed = tk.earnings_dates
    except Exception:
        ed = None
    try:
        cal = tk.calendar or {}
    except Exception:
        cal = {}

    most, history = None, []
    last_report = None  # most recent actual report date (for estimating next)
    if ed is not None and not ed.empty and "Reported EPS" in ed.columns:
        past = ed[ed["Reported EPS"].notna()].sort_index(ascending=False)
        for ts, r in past.head(4).iterrows():
            est, act, sup = _num(r.get("EPS Estimate")), _num(r.get("Reported EPS")), _num(r.get("Surprise(%)"))
            history.append({"q": _qlabel(ts),
                            "est": f"{est:.2f}" if est is not None else "—",
                            "act": f"{act:.2f}" if act is not None else "—",
                            "surprise": _pct(sup, 1) if sup is not None else "—"})
        if not past.empty:
            ts0, r0 = past.index[0], past.iloc[0]
            d = pd.Timestamp(ts0)
            last_report = d
            most = {
                "qtrLabel": f"{((d.month - 1) // 3) + 1}Q FY{d.year}",
                "when": "reported " + d.strftime("%b %d, %Y"),
                "beat": _num(r0.get("Surprise(%)")),
                "epsActual": f"${_num(r0.get('Reported EPS')):.2f}" if _num(r0.get("Reported EPS")) is not None else "—",
                "epsEst": f"{_num(r0.get('EPS Estimate')):.2f}" if _num(r0.get("EPS Estimate")) is not None else "—",
            }
    if most is None:
        # tk.earnings_dates returned nothing (often blocked on cloud IPs). Fall back
        # to the quarterly income-statement EPS already pulled in _financials. No
        # estimate/surprise is available there, so those columns show "—".
        eh = (rev_summary or {}).get("epsHist") or []
        if not eh:
            return None
        d = pd.Timestamp(eh[0]["ts"])
        most = {
            "qtrLabel": f"{((d.month - 1) // 3) + 1}Q FY{d.year}",
            "when": "qtr ended " + d.strftime("%b %d, %Y"),
            "beat": None,
            "epsActual": f"${float(eh[0]['act']):.2f}",
            "epsEst": "—",
        }
        history = [{"q": h["q"], "est": "—", "act": h["act"], "surprise": "—"} for h in eh]

    nextd = "—"
    next_estimated = False
    edates = cal.get("Earnings Date")
    if edates:
        try:
            nextd = pd.Timestamp(edates[0]).strftime("%b %d, %Y")
        except Exception:
            nextd = "—"
    if nextd == "—" and last_report is not None:
        # yfinance's calendar is often empty on cloud IPs; estimate the next
        # report from the actual reporting cadence (last report + one quarter).
        try:
            nextd = (last_report + pd.DateOffset(months=3)).strftime("%b %d, %Y")
            next_estimated = True
        except Exception:
            nextd = "—"
    rev_summary = rev_summary or {}
    most.update({
        "revActual": rev_summary.get("revActual") or "—",
        "revEst": "—",  # yfinance has no reliable historical revenue estimate
        "revYoY": rev_summary.get("revYoY") or "—",
        "next": nextd,
        "nextEstimated": next_estimated,
        "history": history,
    })
    return most


def _news(tk):
    try:
        raw = tk.news or []
    except Exception:
        raw = []
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for item in raw[:8]:
        c = item.get("content", item) if isinstance(item, dict) else {}
        title = c.get("title")
        if not title:
            continue
        prov = c.get("provider")
        publisher = prov.get("displayName") if isinstance(prov, dict) else (c.get("publisher") or "—")
        url = None
        for k in ("canonicalUrl", "clickThroughUrl"):
            if isinstance(c.get(k), dict) and c[k].get("url"):
                url = c[k]["url"]
                break
        url = url or c.get("link") or "#"
        ts = c.get("pubDate") or c.get("displayTime") or item.get("providerPublishTime")
        out.append({"title": title, "publisher": publisher or "—", "ago": _ago(ts, now), "link": url})
    return out or None


_ACTION = {"up": "Upgrade", "down": "Downgrade", "main": "Maintain",
           "reit": "Maintain", "init": "Initiate"}
_CONS_LABEL = [(1.5, "Strong Buy"), (2.5, "Buy"), (3.5, "Hold"), (4.5, "Sell"), (99, "Strong Sell")]


def _research(tk):
    out = {}

    consensus = None
    try:
        rec = tk.recommendations
        if rec is not None and not rec.empty:
            r = rec.iloc[0]
            sb = int(_num(r.get("strongBuy")) or 0)
            b = int(_num(r.get("buy")) or 0)
            h = int(_num(r.get("hold")) or 0)
            sl = int(_num(r.get("sell")) or 0) + int(_num(r.get("strongSell")) or 0)
            total = sb + b + h + sl
            if total:
                mean = (1 * sb + 2 * b + 3 * h + 4.5 * sl) / total
                label = next(lbl for cut, lbl in _CONS_LABEL if mean <= cut)
                consensus = {"total": total, "label": label,
                             "strongBuy": sb, "buy": b, "hold": h, "sell": sl}
    except Exception:
        consensus = None

    try:
        pt = tk.analyst_price_targets or {}
        if consensus is not None and pt:
            consensus.update({"mean": _num(pt.get("mean")), "low": _num(pt.get("low")),
                              "high": _num(pt.get("high")), "current": _num(pt.get("current"))})
    except Exception:
        pass
    if consensus is not None:
        out["consensus"] = consensus

    estimates = []
    try:
        ee = tk.earnings_estimate
        re = tk.revenue_estimate
        period_lbl = {"0q": "Current Qtr", "+1q": "Next Qtr", "0y": "Current Yr", "+1y": "Next Yr"}
        for key, lbl in period_lbl.items():
            if ee is None or key not in ee.index:
                continue
            er = ee.loc[key]
            rr = re.loc[key] if (re is not None and key in re.index) else None
            eps_avg = _num(er.get("avg"))
            rev_avg = _num(rr.get("avg")) if rr is not None else None
            growth = _num(rr.get("growth")) if rr is not None else None
            estimates.append({
                "period": lbl,
                "eps": f"${eps_avg:.2f}" if eps_avg is not None else "—",
                "epsN": str(int(_num(er.get("numberOfAnalysts")))) if _num(er.get("numberOfAnalysts")) is not None else "—",
                "rev": _money(rev_avg) or "—",
                "revYoY": _pct(growth * 100, 0) if growth is not None else "—",
            })
    except Exception:
        estimates = []
    if estimates:
        out["estimates"] = estimates

    actions = []
    try:
        ud = tk.upgrades_downgrades
        if ud is not None and not ud.empty:
            for ts, r in ud.sort_index(ascending=False).head(5).iterrows():
                frm, to = r.get("FromGrade"), r.get("ToGrade")
                grade = f"{frm} → {to}" if frm and to and frm != to else (to or frm or "—")
                tgt = _num(r.get("currentPriceTarget"))
                actions.append({
                    "action": _ACTION.get(str(r.get("Action")), "Update"),
                    "firm": r.get("Firm") or "—",
                    "grade": grade,
                    "target": f"${tgt:.0f}" if tgt is not None else "—",
                    "date": pd.Timestamp(ts).strftime("%b %d"),
                })
    except Exception:
        actions = []
    if actions:
        out["actions"] = actions

    return out or None


# ---------- public ----------
def _fetched_at() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _closed_payload(ticker: str, tk=None) -> dict:
    """Fetch the non-news stock tabs once (used by the nightly job and unowned pages)."""
    tk = tk or yf_ticker(ticker)
    financials, rev_summary = _financials(tk)
    return {
        "ticker": ticker,
        "financials": financials,
        "earnings": _earnings(tk, rev_summary),
        "research": _research(tk),
        "fetchedAt": _fetched_at(),
    }


def refresh_closed_snapshot(ticker: str) -> dict:
    """Refresh a current holding's nightly, last-known-good research snapshot.

    An all-empty response is treated as an upstream failure and never overwrites
    the prior snapshot.
    """
    t = ticker.upper()
    payload = _closed_payload(t)
    if any(payload.get(k) for k in ("financials", "earnings", "research")):
        cache.set("stock_closed", t, payload, _SNAPSHOT_TTL)
    return payload


def closed_snapshot(ticker: str) -> dict:
    """Read a holding snapshot without ever contacting yfinance."""
    t = ticker.upper()
    cached = cache.peek("stock_closed", t)
    if cached is not cache.MISS:
        value, _age = cached
        return {**value, "ticker": t, "news": None, "snapshotPending": False}
    return {
        "ticker": t,
        "financials": None,
        "earnings": None,
        "news": None,
        "research": None,
        "fetchedAt": None,
        "snapshotPending": True,
    }


def stock_news(ticker: str, *, force: bool = False) -> dict:
    """Short-TTL news with stale-on-error behavior for owned and unowned names."""
    t = ticker.upper()
    now = time.time()
    hit = _NEWS_CACHE.get(t)
    if not force and hit and (now - hit[0]) < _NEWS_TTL:
        return {**hit[1], "ticker": t, "cached": True}
    if not force:
        cached = cache.get("stock_news", t)
        if cached is not cache.MISS:
            value, age = cached
            _NEWS_CACHE[t] = (now - age, value)
            return {**value, "ticker": t, "cached": True}

    payload = {"ticker": t, "news": _news(yf_ticker(t)) or [],
               "fetchedAt": _fetched_at(), "cached": False}
    if payload["news"]:
        _NEWS_CACHE[t] = (now, payload)
        cache.set("stock_news", t, payload, _NEWS_TTL)
        return payload

    # Yahoo errors and genuinely empty feeds look the same through yfinance.
    # Prefer the last successful headlines to a blank tab.
    stale = cache.peek("stock_news", t)
    if stale is not cache.MISS:
        value, _age = stale
        return {**value, "ticker": t, "cached": True, "stale": True}
    return payload


def stock_research(ticker: str) -> dict:
    """Full on-demand yfinance bundle for a ticker that is not currently owned."""
    ticker = ticker.upper()
    now = time.time()
    hit = _CACHE.get(ticker)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    cached = cache.get("research", ticker)
    if cached is not cache.MISS:
        value, age = cached
        _CACHE[ticker] = (now - age, value)
        return value

    tk = yf_ticker(ticker)
    payload = _closed_payload(ticker, tk)
    news = _news(tk) or []
    payload["news"] = news
    if not any(payload.get(k) for k in ("financials", "earnings", "news", "research")):
        stale = cache.peek("research", ticker)
        if stale is not cache.MISS:
            value, _age = stale
            return {**value, "ticker": ticker, "stale": True}
    _CACHE[ticker] = (now, payload)
    # Persist only when a section actually resolved, so a transient yfinance
    # failure (every section empty) doesn't poison the shared cache for 15 min.
    if any(payload[k] for k in ("financials", "earnings", "news", "research")):
        cache.set("research", ticker, payload, _TTL)
    if news:
        news_payload = {"ticker": ticker, "news": news,
                        "fetchedAt": payload["fetchedAt"], "cached": False}
        _NEWS_CACHE[ticker] = (now, news_payload)
        cache.set("stock_news", ticker, news_payload, _NEWS_TTL)
    return payload
