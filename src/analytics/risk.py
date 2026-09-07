"""Beta and related risk metrics from current holdings.

No portfolio NAV history is available, so fund beta is built bottom-up: each
holding's beta is the regression of its daily returns on its fund's benchmark
(Tall Firs -> IWV / Russell 3000, Alumni -> IWM / Russell 2000) over the
configured window (default 3 years daily), and fund beta is the
portfolio-weighted average of constituent betas (index overlay beta = 1, cash
beta = 0). A synthetic "current-weights" portfolio return series, regressed on
the benchmark, provides a cross-check plus R^2 and annualized volatility.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from src.config import db_path
from src.model.schema import get_connection

MIN_OBS = 60          # minimum overlapping days to report a beta
TRADING_DAYS = 252


def daily_returns_matrix(conn: sqlite3.Connection, years: float) -> pd.DataFrame:
    """Wide (date x ticker) daily simple returns over the trailing window."""
    p = pd.read_sql(
        "SELECT ticker, date, adj_close FROM prices WHERE source = 'yfinance'", conn)
    if p.empty:
        return pd.DataFrame()
    p["date"] = pd.to_datetime(p["date"])
    cutoff = p["date"].max() - pd.Timedelta(days=int(years * 365.25))
    p = p[p["date"] >= cutoff]
    wide = p.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    return wide.pct_change()


def _beta(stock: pd.Series, bench: pd.Series) -> tuple[float, float, float, int]:
    """OLS beta of stock on bench: beta = cov(s,b)/var(b). Returns (beta, alpha, r2, n)."""
    d = pd.concat([stock, bench], axis=1, keys=["s", "b"]).dropna()
    n = len(d)
    if n < MIN_OBS:
        return (np.nan, np.nan, np.nan, n)
    var = d["b"].var(ddof=1)
    if not var or np.isnan(var):
        return (np.nan, np.nan, np.nan, n)
    beta = d["s"].cov(d["b"]) / var
    alpha = d["s"].mean() - beta * d["b"].mean()
    r2 = (d["s"].corr(d["b"]) ** 2) if d["s"].std(ddof=1) > 0 else np.nan
    return (float(beta), float(alpha), float(r2), n)


def add_betas(positions: pd.DataFrame, rets: pd.DataFrame) -> pd.DataFrame:
    """Append beta, alpha, r2, n_obs, beta_contrib per position."""
    df = positions.copy()
    res = []
    for row in df.itertuples():
        if row.sec_type == "cash":
            res.append((0.0, np.nan, np.nan, 0))
        elif row.sec_type == "etf":
            res.append((1.0, 0.0, 1.0, 0))   # index overlay == its own benchmark
        elif (row.bench_ticker in rets.columns) and (row.ticker in rets.columns):
            res.append(_beta(rets[row.ticker], rets[row.bench_ticker]))
        else:
            res.append((np.nan, np.nan, np.nan, 0))
    df[["beta", "alpha", "r2", "n_obs"]] = pd.DataFrame(res, index=df.index)
    df["beta_contrib"] = df["port_w"] * df["beta"]
    return df


def fund_risk_table(positions: pd.DataFrame, rets: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Per-fund weighted beta, active-sleeve beta, synthetic-series beta/R^2/vol."""
    bench_map = {f["name"]: f["benchmark"] for f in cfg["funds"]}
    out = []
    for fund, g in positions.groupby("fund"):
        bench = bench_map.get(fund)

        m = g["port_w"].notna() & g["beta"].notna()
        wbeta = (float((g.loc[m, "port_w"] * g.loc[m, "beta"]).sum() / g.loc[m, "port_w"].sum())
                 if m.any() else np.nan)

        s = g[g.sec_type == "stock"]
        ms = s["class_w"].notna() & s["beta"].notna()
        abeta = (float((s.loc[ms, "class_w"] * s.loc[ms, "beta"]).sum() / s.loc[ms, "class_w"].sum())
                 if ms.any() else np.nan)

        syn_beta = syn_r2 = ann_vol = np.nan
        cols = [t for t in g.loc[m, "ticker"] if t in rets.columns]
        if cols and bench in rets.columns:
            w = g.set_index("ticker").loc[cols, "port_w"]
            w = w / w.sum()
            port = rets[cols].mul(w, axis=1).sum(axis=1, min_count=1)
            syn_beta, _, syn_r2, _ = _beta(port, rets[bench])
            ann_vol = float(port.dropna().std(ddof=1) * np.sqrt(TRADING_DAYS))

        out.append({"fund": fund, "benchmark": bench, "beta": wbeta,
                    "active_beta": abeta, "syn_beta": syn_beta,
                    "r2": syn_r2, "ann_vol": ann_vol})
    return pd.DataFrame(out)


def load_risk(cfg: dict, positions: pd.DataFrame,
              conn: sqlite3.Connection | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (positions_with_beta, fund_risk_table)."""
    own = conn is None
    if own:
        conn = get_connection(db_path(cfg))
    try:
        years = (cfg.get("risk") or {}).get("beta_window_years", 3)
        rets = daily_returns_matrix(conn, years)
    finally:
        if own:
            conn.close()
    pos = add_betas(positions, rets)
    return pos, fund_risk_table(pos, rets, cfg)
