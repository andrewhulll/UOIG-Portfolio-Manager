"""Assemble the terminal view-model (funds + holdings) from the analytics layer.

Field names mirror the redesign's data shapes so the React frontend maps almost
1:1. Fund-level period returns use the synthetic current-weights series (no NAV
history); per-stock figures and benchmark returns use real price history.
"""
from __future__ import annotations

import datetime as dt
import math
import sqlite3

import pandas as pd

from src.analytics.pnl import load_positions
from src.analytics.returns import enrich_returns
from src.analytics.risk import _beta, add_betas, daily_returns_matrix, fund_risk_table
from src.analytics.series import (PERIODS, div_yield_ttm, mtd_return, period_return,
                                  price_frame, ticker_series)
from src.model import schema as _schema

# fund key + display styling
FUND_META = {
    "Tall Firs": {"key": "tallfirs", "color": "#5a93f9", "benchShort": "Russell 3000"},
    "Alumni Fund": {"key": "alumni", "color": "#f4a531", "benchShort": "Russell 2000"},
}


def _clean(x):
    """JSON-safe float (None for NaN/inf)."""
    if x is None:
        return None
    try:
        f = float(x)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    except (TypeError, ValueError):
        return None


def _port_daily(rets: pd.DataFrame, weights: dict) -> pd.Series:
    cols = [t for t in weights if t in rets.columns]
    if not cols:
        return pd.Series(dtype=float)
    w = pd.Series({t: weights[t] for t in cols})
    w = w / w.sum()
    return rets[cols].mul(w, axis=1).sum(axis=1, min_count=1).dropna()


def _synth_period_ret(rets: pd.DataFrame, weights: dict, period: str):
    """Reconstructed current-weights fund total return over the period."""
    if rets.empty:
        return None
    start = pd.Timestamp(_pstart(rets, period))
    s = _port_daily(rets.loc[rets.index >= start, :], weights)
    return ((1 + s).prod() - 1) if len(s) else None


def _wavg(pairs):
    num = sum(w * v for w, v in pairs if v is not None)
    den = sum(w for w, v in pairs if v is not None)
    return num / den if den else None


def build_terminal_data(cfg: dict, conn: sqlite3.Connection) -> dict:
    _schema.create_schema(conn)  # idempotent; ensures latest migrated columns exist
    pos = enrich_returns(load_positions(cfg, conn), conn)
    rets = daily_returns_matrix(conn, (cfg.get("risk") or {}).get("beta_window_years", 3))
    pos = add_betas(pos, rets)
    frisk = fund_risk_table(pos, rets, cfg).set_index("fund")
    pf = price_frame(conn)
    fund_map = {f["name"]: f["benchmark"] for f in cfg["funds"]}

    funda = {r[0]: r for r in conn.execute(
        "SELECT ticker, gics_sector, pe, pb, market_cap, week52_low, week52_high, "
        "description, ev_ebitda, div_yield_provider FROM fundamentals").fetchall()}

    def _dy(ticker, px):
        # #43: our dividends table first; fall back to the provider's reported
        # TTM yield (backfilled by the fundamentals refresh) when it has nothing.
        db_yield = div_yield_ttm(conn, ticker, px)
        if db_yield:
            return db_yield
        row = funda.get(ticker)
        return row[9] if row else None

    rf = period_return(pf, (cfg.get("risk") or {}).get("risk_free", "BIL"), "1Y") or 0.04

    # ---- holdings (stocks + index overlay; cash excluded) ----
    holdings = []
    for r in pos[pos.sec_type != "cash"].itertuples():
        meta = FUND_META.get(r.fund, {})
        fd = funda.get(r.ticker)
        px = _clean(r.price)
        sector = (fd[1] if fd and fd[1] else ("Index ETF" if r.sec_type == "etf" else r.sector))
        holdings.append({
            "t": r.ticker, "n": r.name, "s": sector, "fund": meta.get("key", r.fund),
            "w": _clean((r.port_w or 0) * 100),
            "px": px,
            "mv": _clean(r.market_value),   # shares × price, USD
            "sh": _clean(r.shares),
            "chg": _clean((r.day_chg_pct or 0) * 100),
            "mtd": _clean((mtd_return(pf, r.ticker) or 0) * 100),
            "pe": _clean(fd[2]) if fd else None,
            "pb": _clean(fd[3]) if fd else None,
            "evEbitda": _clean(fd[8]) if fd else None,
            "dy": _clean(_dy(r.ticker, px)),
            "beta": _clean(r.beta),
            "mc": _clean(fd[4] / 1e9) if fd and fd[4] else None,   # $B
            "lo": _clean(fd[5]) if fd else None,
            "hi": _clean(fd[6]) if fd else None,
            "desc": (fd[7] if fd else "") or "",
            # 3M of downsampled closes for the holdings-table sparkline column
            "spark": ticker_series(pf, r.ticker, "3M", points=30)["close"],
        })

    # Total-portfolio weight for the All Funds view (#28): port_w above is
    # fund-relative, so the combined view showed each fund's internal weight.
    total_mv = sum(h["mv"] for h in holdings if h["mv"])
    for h in holdings:
        h["wAll"] = round(h["mv"] / total_mv * 100, 2) if total_mv and h["mv"] else 0.0

    # ---- funds ----
    funds = {}
    for f in cfg["funds"]:
        name, bench = f["name"], f["benchmark"]
        meta = FUND_META.get(name, {})
        fpos = pos[pos.fund == name]
        stocks = fpos[fpos.sec_type == "stock"]
        weights = {r.ticker: r.port_w for r in fpos[fpos.sec_type != "cash"].itertuples()
                   if r.port_w and not pd.isna(r.port_w)}

        ret = {p: _clean(_synth_period_ret(rets, weights, p)) for p in PERIODS}
        bret = {p: _clean(period_return(pf, bench, p)) for p in PERIODS}

        # alpha/beta from 3y daily synthetic regression
        port = _port_daily(rets, weights)
        b, a_daily, r2, _ = _beta(port, rets[bench]) if bench in rets.columns else (None, None, None, 0)
        ann_vol = frisk.loc[name, "ann_vol"] if name in frisk.index else None
        wbeta = frisk.loc[name, "beta"] if name in frisk.index else b
        ann_ret = ret.get("1Y")
        sharpe = ((ann_ret - rf) / ann_vol) if (ann_ret is not None and ann_vol) else None

        funds[meta.get("key", name)] = {
            "key": meta.get("key", name), "name": name,
            "long": f"{name} · Net Asset Value",
            "bench": meta.get("benchShort", bench), "benchShort": meta.get("benchShort", bench),
            "benchTicker": bench, "color": meta.get("color", "#5a93f9"),
            "aum": _clean(fpos["market_value"].sum() / 1e6),   # $M
            "ret": ret, "bret": bret,
            "alpha": _clean((a_daily or 0) * 252 * 100),
            "beta": _clean(wbeta), "sharpe": _clean(sharpe),
            "vol": _clean((ann_vol or 0) * 100),
            "pe": _clean(_wavg([(r.port_w, funda.get(r.ticker, [None]*3)[2] if funda.get(r.ticker) else None)
                                for r in stocks.itertuples()])),
            "pb": _clean(_wavg([(r.port_w, funda.get(r.ticker, [None]*4)[3] if funda.get(r.ticker) else None)
                                for r in stocks.itertuples()])),
            "dy": _clean(_wavg([(r.port_w, _dy(r.ticker, r.price))
                                for r in stocks.itertuples()])),
        }

    return {
        "funds": funds, "holdings": holdings,
        "asOf": (conn.execute("SELECT value FROM import_meta WHERE key='last_refresh'").fetchone()
                 or [dt.date.today().isoformat()])[0],
        "note": "Fund period returns are reconstructed from current holdings (no NAV history).",
    }


def _pstart(rets: pd.DataFrame, period: str):
    from src.analytics.series import period_start
    return period_start(rets.index.max().date(), period)
