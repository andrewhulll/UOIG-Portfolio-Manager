"""Holding-period returns and benchmark-relative performance.

Computed entirely from current holdings + daily price history — no NAV series
required. For each name we measure total return (dividend-reinvested, via
adjusted close) over its own holding window (entry date -> latest), the matching
benchmark return over the same window, and the excess. Roll-ups weight by the
class (active-sleeve) weight.

Returns here use adjusted close for both the stock and its benchmark so the
excess is apples-to-apples; this can differ marginally from the holdings table's
simple "total return since entry" (entry price + dividends collected).
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from src.config import db_path
from src.model.schema import get_connection


def _wavg(values: pd.Series, weights: pd.Series) -> float:
    m = values.notna() & weights.notna()
    total = weights[m].sum()
    return float((values[m] * weights[m]).sum() / total) if total else np.nan


def enrich_returns(positions: pd.DataFrame, conn: sqlite3.Connection) -> pd.DataFrame:
    """Add days_held, hp_tr, bench_tr, excess_tr, ann_tr, contribution per position."""
    prices = pd.read_sql(
        "SELECT ticker, date, adj_close FROM prices WHERE source = 'yfinance'", conn)
    prices["date"] = pd.to_datetime(prices["date"])
    by = {t: g.set_index("date")["adj_close"].sort_index()
          for t, g in prices.groupby("ticker")}
    last_date = prices["date"].max() if not prices.empty else pd.NaT

    df = positions.copy()
    df["entry_dt"] = pd.to_datetime(df["entry_date"], errors="coerce")

    def window(row) -> pd.Series:
        blank = pd.Series({"days_held": np.nan, "hp_tr": np.nan, "bench_tr": np.nan,
                           "excess_tr": np.nan, "ann_tr": np.nan})
        if row.sec_type != "stock" or pd.isna(row.entry_dt):
            return blank
        s, b = by.get(row.ticker), by.get(row.bench_ticker)
        hp = bench = np.nan
        if s is not None and len(s):
            se = s[s.index >= row.entry_dt]
            if len(se):
                hp = s.iloc[-1] / se.iloc[0] - 1
        if b is not None and len(b):
            be = b[b.index >= row.entry_dt]
            if len(be):
                bench = b.iloc[-1] / be.iloc[0] - 1
        days = (last_date - row.entry_dt).days if pd.notna(last_date) else np.nan
        ann = ((1 + hp) ** (365 / days) - 1
               if pd.notna(hp) and pd.notna(days) and days > 0 and (1 + hp) > 0 else np.nan)
        excess = hp - bench if pd.notna(hp) and pd.notna(bench) else np.nan
        return pd.Series({"days_held": days, "hp_tr": hp, "bench_tr": bench,
                          "excess_tr": excess, "ann_tr": ann})

    df = pd.concat([df, df.apply(window, axis=1)], axis=1)
    df["contribution"] = df["class_w"] * df["hp_tr"]
    return df


def load_returns(cfg: dict, conn: sqlite3.Connection | None = None,
                 positions: pd.DataFrame | None = None) -> pd.DataFrame:
    own = conn is None
    if own:
        conn = get_connection(db_path(cfg))
    try:
        if positions is None:
            from src.analytics.pnl import load_positions
            positions = load_positions(cfg, conn)
        return enrich_returns(positions, conn)
    finally:
        if own:
            conn.close()


def fund_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Per-fund active-sleeve holding-period return, annualized, and excess."""
    out = []
    for fund, g in df.groupby("fund"):
        s = g[g.sec_type == "stock"]
        out.append({
            "fund": fund,
            "hp_return": _wavg(s["hp_tr"], s["class_w"]),
            "ann_return": _wavg(s["ann_tr"], s["class_w"]),
            "excess": _wavg(s["excess_tr"], s["class_w"]),
            "names": int(s.shape[0]),
        })
    return pd.DataFrame(out)


def sector_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Per-sector weight, weighted return, and contribution (active sleeve)."""
    s = df[df.sec_type == "stock"]
    out = []
    for sec, g in s.groupby("sector"):
        out.append({
            "sector": sec,
            "weight": g["class_w"].sum(),
            "return": _wavg(g["hp_tr"], g["class_w"]),
            "contribution": (g["class_w"] * g["hp_tr"]).sum(skipna=True),
        })
    return pd.DataFrame(out).sort_values("contribution", ascending=False)
