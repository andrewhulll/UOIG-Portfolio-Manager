"""Position- and fund-level P&L from the store.

Computes market value, unrealized P&L, day change, dividend-inclusive total
return since entry, and the fund weights (class / portfolio / active) using the
exact definitions from the legacy sheet:

    class weight     = MV / (invested capital - index overlay)   [active sleeve]
    portfolio weight = MV / invested capital                     [excl. cash]
    active weight    = portfolio weight - passive (benchmark) weight
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from src.config import db_path
from src.model.schema import get_connection


def _latest_two(conn: sqlite3.Connection) -> pd.DataFrame:
    """Latest and previous close per ticker.

    Live (yfinance) prices win over the xlsx snapshot regardless of date — the
    snapshot is dated 'today' but is the stale manually-entered sheet price, so
    it is used only as a fallback for tickers with no live data (i.e. cash).
    """
    p = pd.read_sql("SELECT ticker, date, close, source FROM prices", conn)
    if p.empty:
        return pd.DataFrame(columns=["ticker", "price", "prev_close"])

    live = p[p.source != "xlsx_snapshot"].sort_values(["ticker", "date"])
    last2 = live.groupby("ticker").tail(2)
    res = pd.concat([
        last2.groupby("ticker").tail(1).set_index("ticker")["close"].rename("price"),
        last2.groupby("ticker").head(1).set_index("ticker")["close"].rename("prev_close"),
    ], axis=1)
    res.index.name = "ticker"

    snap = (p[p.source == "xlsx_snapshot"].sort_values(["ticker", "date"])
            .groupby("ticker").tail(1).set_index("ticker")["close"])
    for tk, close in snap.items():
        if tk not in res.index:
            res.loc[tk] = {"price": close, "prev_close": close}

    # Live intraday override: a fresh latest quote from the background poller
    # (src.ingest.live_prices) wins over the nightly DB close so spot price, day
    # change, weights and AUM are current. Quotes go stale outside market hours,
    # so this is a no-op when the market is closed (DB close is used instead).
    try:
        from src.ingest.live_prices import overrides as _live_overrides
        for tk, q in _live_overrides().items():
            if tk in res.index:
                res.loc[tk, "price"] = q["price"]
                res.loc[tk, "prev_close"] = q["prev_close"]
    except Exception:  # noqa: BLE001 — analytics must not depend on the poller
        pass

    return res.reset_index()


def _add_weights(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("class_w", "port_w", "active_w"):
        df[col] = np.nan
    for _, g in df.groupby("fund"):
        total = g["market_value"].sum()
        cash = g.loc[g.sec_type == "cash", "market_value"].sum()
        index = g.loc[g.sec_type == "etf", "market_value"].sum()
        invested = total - cash
        active_sleeve = total - cash - index
        non_cash = g.index[g.sec_type != "cash"]
        stocks = g.index[g.sec_type == "stock"]
        df.loc[non_cash, "port_w"] = df.loc[non_cash, "market_value"] / invested
        df.loc[stocks, "class_w"] = df.loc[stocks, "market_value"] / active_sleeve
        df.loc[stocks, "active_w"] = df.loc[stocks, "port_w"] - df.loc[stocks, "passive_weight"]
    return df


def load_positions(cfg: dict, conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    own = conn is None
    if own:
        conn = get_connection(db_path(cfg))
    try:
        df = pd.read_sql(
            "SELECT h.fund, h.ticker, h.shares, h.entry_price, h.entry_date,"
            " h.passive_weight, h.bench_ticker, s.name, s.sector, s.cap_class, s.sec_type"
            " FROM holdings h JOIN securities s ON s.ticker = h.ticker", conn)
        px = _latest_two(conn)
        divs = pd.read_sql("SELECT ticker, ex_date, amount FROM dividends", conn)
    finally:
        if own:
            conn.close()

    df = df.merge(px, on="ticker", how="left")

    # dividends per share accumulated since each holding's entry date
    def div_ps(row):
        if not row["entry_date"] or divs.empty:
            return 0.0
        d = divs[(divs.ticker == row.ticker) & (divs.ex_date >= row.entry_date)]
        return float(d["amount"].sum())

    df["div_ps"] = df.apply(div_ps, axis=1)

    df["market_value"] = df["shares"] * df["price"]
    df["day_chg"] = df["shares"] * (df["price"] - df["prev_close"])
    df["day_chg_pct"] = df["price"] / df["prev_close"] - 1

    # Entry-based P&L is only meaningful for the active stock picks. The index
    # overlay (IWV/IWM) and cash have no reliable cost basis in the sheet, so
    # their since-entry P&L is N/A; they still count toward AUM and day change,
    # and total fund performance is captured by TWR from NAV (Phase 2).
    df["cost_basis"] = df["shares"] * df["entry_price"]
    df["unreal_pnl"] = df["market_value"] - df["cost_basis"]
    df["unreal_pnl_pct"] = df["price"] / df["entry_price"] - 1
    df["total_ret_pct"] = (df["price"] + df["div_ps"]) / df["entry_price"] - 1
    non_stock = df["sec_type"] != "stock"
    df.loc[non_stock, ["cost_basis", "unreal_pnl", "unreal_pnl_pct", "total_ret_pct"]] = np.nan

    return _add_weights(df)


def fund_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-fund roll-up.

    market_value = total AUM (stocks + index overlay + cash).
    unrealized P&L = active stock sleeve only (positions with a real cost basis).
    """
    rows = []
    for fund, g in df.groupby("fund"):
        stocks = g[g["sec_type"] == "stock"]
        mv = g["market_value"].sum()
        prev_mv = (g["prev_close"] * g["shares"]).sum()
        active_mv = stocks["market_value"].sum()
        active_cost = stocks["cost_basis"].sum()
        rows.append({
            "fund": fund,
            "market_value": mv,
            "day_chg": g["day_chg"].sum(),
            "day_chg_pct": (mv / prev_mv - 1) if prev_mv else np.nan,
            "active_mv": active_mv,
            "active_cost": active_cost,
            "unreal_pnl": active_mv - active_cost,
            "unreal_pnl_pct": (active_mv / active_cost - 1) if active_cost else np.nan,
            "positions": len(g),
        })
    return pd.DataFrame(rows)
