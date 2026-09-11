"""Coverage position facts and current-weight contribution estimates. No network."""
from datetime import timedelta
import math

import pandas as pd

from src.analytics.pnl import load_positions
from src.analytics.series import price_frame
from src.analytics.optimize import _uoig_group
from src.model import db

FUNDS = {"tallfirs": "Tall Firs", "alumni": "Alumni Fund"}


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def fundamental_rows(conn):
    cur = conn.execute("SELECT ticker, forward_pe, revenue_growth, exchange, volume, "
                       "average_volume, market_cap, week52_low, week52_high, updated FROM fundamentals")
    columns = [c[0] for c in cur.description]
    return {r[0]: dict(zip(columns, r)) for r in cur.fetchall()}


def context(cfg, conn, fund="all"):
    if fund not in {"all", *FUNDS}:
        raise ValueError("fund must be all, tallfirs, or alumni")
    names = list(FUNDS.values()) if fund == "all" else [FUNDS[fund]]
    if conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]:
        pos = load_positions(cfg, conn)
        pos = pos[(pos.shares > 0) & pos.fund.isin(names) & (pos.sec_type != "cash")].copy()
    else:
        pos = pd.DataFrame(columns=["fund", "ticker", "shares", "market_value", "sec_type", "sector", "entry_price", "price", "passive_weight"])
    capitals = {}
    for name, g in pos.groupby("fund"):
        vals = [number(v) for v in g.market_value]
        capitals[name] = sum(vals) if all(v is not None for v in vals) else None
    total = sum(capitals.values()) if all(v is not None for v in capitals.values()) else None
    benchmarks = {}
    for f in cfg.get("funds", []):
        if f["name"] in names:
            rows = conn.execute(db.q(conn, "SELECT ticker, weight FROM benchmark_holdings WHERE index_ticker=?"), (f["benchmark"],)).fetchall()
            benchmarks[f["name"]] = {r[0]: number(r[1]) for r in rows}
    facts = fundamental_rows(conn)
    sectors = {}
    for r in pos[pos.sec_type == "stock"].itertuples():
        group = _uoig_group(r.sector)
        pe = number(facts.get(r.ticker, {}).get("forward_pe"))
        mv = number(r.market_value)
        if group and pe is not None and pe > 0 and mv is not None and mv > 0:
            num, den = sectors.get(group, (0, 0))
            sectors[group] = (num + pe * mv, den + mv)
    return {"positions": pos, "capitals": capitals, "total": total,
            "benchmarks": benchmarks, "facts": facts,
            "sectors": {k: n / d for k, (n, d) in sectors.items()}}


def position_facts(ctx, ticker, sector=None):
    pos, total = ctx["positions"], ctx["total"]
    held = pos[pos.ticker == ticker]
    out = {"heldInFund": not held.empty, "weight": None, "activeWeightBp": None,
           "costBasis": None, "unrealized": None,
           "sectorForwardPE": ctx["sectors"].get(_uoig_group(sector))}
    if held.empty:
        return out
    values = [number(v) for v in held.market_value]
    mv = sum(values) if all(v is not None for v in values) else None
    weight = mv / total if total and mv is not None else None
    out["weight"] = weight * 100 if weight is not None else None
    # An unknown basis in one fund must not silently become a partial sum.
    bases = [number(v) for v in held.entry_price]
    if all(v is not None and v > 0 for v in bases) and (held.sec_type == "stock").all():
        basis = sum(float(r.shares) * float(r.entry_price) for r in held.itertuples())
        out["costBasis"] = basis / float(held.shares.sum())
        out["unrealized"] = mv - basis if mv is not None else None
    exposure = 0.0
    if weight is not None:
        for name, capital in ctx["capitals"].items():
            if not capital:
                continue
            benchmark = ctx["benchmarks"].get(name, {})
            if benchmark:
                bw = benchmark.get(ticker, 0.0)
            else:
                row = held[held.fund == name]
                bw = number(row.passive_weight.iloc[0]) if len(row) else None
            if bw is None:
                break
            exposure += capital / total * bw
        else:
            out["activeWeightBp"] = (weight - exposure) * 10000
    return out


def movers(cfg, conn, fund="all", window="MTD"):
    if window not in {"1W", "MTD", "QTD"}:
        raise ValueError("window must be 1W, MTD, or QTD")
    ctx = context(cfg, conn, fund)
    pos, total = ctx["positions"], ctx["total"]
    tickers = sorted(set(pos.ticker))
    pf = price_frame(conn)
    pf = pf[pf.ticker.isin(tickers)]
    as_of = pf.date.max().date() if not pf.empty else None
    boundary = None
    if as_of:
        boundary = (as_of - timedelta(days=7) if window == "1W" else
                    as_of.replace(day=1) - timedelta(days=1) if window == "MTD" else
                    as_of.replace(month=((as_of.month - 1) // 3) * 3 + 1, day=1) - timedelta(days=1))
    rows, missing = [], []
    for ticker in tickers:
        history = pf[pf.ticker == ticker]
        before = history[history.date.dt.date <= boundary] if boundary else history.iloc[:0]
        end = history[history.date.dt.date == as_of] if as_of else history.iloc[:0]
        base = number(before.adj_close.iloc[-1]) if len(before) else None
        last = number(end.adj_close.iloc[-1]) if len(end) else None
        holding = pos[pos.ticker == ticker]
        vals = [number(v) for v in holding.market_value]
        mv = sum(vals) if all(v is not None for v in vals) else None
        if not total or not base or base <= 0 or last is None or last <= 0 or mv is None:
            missing.append(ticker)
            continue
        ret = last / base - 1
        rows.append({"ticker": ticker, "pct": round(ret * 100, 4),
                     "contribution_bp": round(mv / total * ret * 10000, 4),
                     "startDate": before.date.iloc[-1].date().isoformat()})
    return {"fund": fund, "fundName": "All Funds" if fund == "all" else FUNDS[fund],
            "window": window, "asOf": as_of.isoformat() if as_of else None,
            "startDate": boundary.isoformat() if boundary else None,
            "contributors": sorted([r for r in rows if r["contribution_bp"] > 0], key=lambda r: (-r["contribution_bp"], r["ticker"]))[:5],
            "detractors": sorted([r for r in rows if r["contribution_bp"] < 0], key=lambda r: (r["contribution_bp"], r["ticker"]))[:5],
            "missingTickers": missing, "includedCount": len(rows), "totalCount": len(tickers)}
