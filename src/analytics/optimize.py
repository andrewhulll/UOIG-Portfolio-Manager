"""Per-fund portfolio diagnostics, what-if analytics and Black-Litterman
optimization for the optimization page.

Everything here is framed as ACTIVE risk versus the fund's benchmark (Tall Firs
-> IWV, Alumni -> IWM), which is how the club actually manages the books:

  tracking error    realized std of (fund - benchmark) daily returns, annualized
  beta / vol        fund beta vs its benchmark; total annualized vol
  active share      0.5 * sum |w_port - w_bench| over the union of names
  risk contribution each holding's share of active risk, from a' Σ a on the
                    active weights (an ex-ante decomposition over held names)
  sector tilts      portfolio minus benchmark weight per UOIG sector group
  concentration     HHI, effective number of names, top-5 weight

Benchmark constituent + sector weights come from the ``benchmark_holdings`` /
``benchmark_sectors`` tables (Alpha Vantage ETF_PROFILE, see
``src.ingest.benchmark_holdings``). Return-series inputs reuse the existing
analytics layer (``daily_returns_matrix``). Nothing here mutates state.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from src.analytics.pnl import load_positions
from src.analytics.risk import _beta, daily_returns_matrix
from src.model import db as _db

TRADING_DAYS = 252


UOIG_GROUPS = ["TMT", "IME", "Healthcare", "Financial", "Consumer"]
# Our securities table already tags each stock with its UOIG group name; the
# Alpha Vantage benchmark feed uses standard GICS sector names. Map both.
_EXACT = {g.lower(): g for g in UOIG_GROUPS}


def _uoig_group(sector: str | None) -> str | None:
    """Map a sector label — our own UOIG group name OR a GICS sector (yfinance or
    standard-GICS spelling, any case) — to one of the five UOIG groups. Returns
    None for cash / index overlay / unmapped."""
    if not sector:
        return None
    s = sector.strip().lower()
    if s in _EXACT:
        return _EXACT[s]
    if "technolog" in s or "communication" in s:
        return "TMT"
    if "industrial" in s or "utilit" in s or "material" in s or "energy" in s:
        return "IME"
    if "health" in s:
        return "Healthcare"
    if "financ" in s or "real estate" in s:
        return "Financial"
    if "consumer" in s:
        return "Consumer"
    return None


def _bench_weights(conn, index_ticker: str) -> dict[str, float]:
    """{ticker: weight} for a benchmark's constituents (weight as a fraction)."""
    rows = conn.execute(
        _db.q(conn, "SELECT ticker, weight FROM benchmark_holdings WHERE index_ticker = ?"),
        (index_ticker,)).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def _bench_sector_groups(conn, index_ticker: str) -> dict[str, float]:
    """Benchmark weight per UOIG group, from the provider's sector allocation."""
    rows = conn.execute(
        _db.q(conn, "SELECT sector, weight FROM benchmark_sectors WHERE index_ticker = ?"),
        (index_ticker,)).fetchall()
    out: dict[str, float] = {g: 0.0 for g in UOIG_GROUPS}
    for sector, w in rows:
        g = _uoig_group(sector)
        if g and w is not None:
            out[g] += float(w)
    return out


def _fund_daily(rets: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Current-weights daily return series over names we have returns for."""
    cols = [t for t in weights if t in rets.columns]
    if not cols:
        return pd.Series(dtype=float)
    w = pd.Series({t: weights[t] for t in cols})
    w = w / w.sum()
    return rets[cols].mul(w, axis=1).sum(axis=1, min_count=1)


def fund_diagnostics(cfg: dict, conn: sqlite3.Connection, fund_name: str) -> dict:
    """The full diagnostics payload for one fund, framed vs its benchmark."""
    bench = next((f["benchmark"] for f in cfg["funds"] if f["name"] == fund_name), None)
    if bench is None:
        raise ValueError(f"unknown fund {fund_name!r}")

    years = (cfg.get("risk") or {}).get("beta_window_years", 3)
    rets = daily_returns_matrix(conn, years)

    pos = load_positions(cfg, conn)
    g = pos[(pos.fund == fund_name) & (pos.sec_type != "cash")].copy()
    names = {r.ticker: r.name for r in g.itertuples()}

    # Split the sleeve: individual stocks are the active bets; any index ETF is a
    # PASSIVE OVERLAY that tracks the benchmark. All weights are fractions of the
    # invested (ex-cash) book, so stock weights + overlay weight `o` sum to ~1.
    all_w = {r.ticker: float(r.port_w) for r in g.itertuples() if r.port_w == r.port_w}
    tot = sum(all_w.values()) or 1.0
    all_w = {t: w / tot for t, w in all_w.items()}
    stock_w = {r.ticker: all_w[r.ticker] for r in g.itertuples()
               if r.sec_type == "stock" and r.ticker in all_w}
    overlay = 1.0 - sum(stock_w.values())  # benchmark-tracking fraction
    sectors = {r.ticker: r.sector for r in g.itertuples()}

    bench_w = _bench_weights(conn, bench)
    # Look-through active weight of a held stock: its direct weight minus the
    # benchmark exposure the non-overlay part of the book "should" carry. A pure
    # overlay (overlay=1) yields zero active weight everywhere, as it must.
    def active_w(t: str) -> float:
        return stock_w.get(t, 0.0) - (1.0 - overlay) * bench_w.get(t, 0.0)

    # ---- return-series metrics (realized, uses the whole book incl. overlay) ----
    fund_ret = _fund_daily(rets, all_w)
    te = beta = vol = None
    if not fund_ret.empty and bench in rets.columns:
        pair = pd.concat([fund_ret, rets[bench]], axis=1, keys=["f", "b"]).dropna()
        if len(pair) >= 2:
            active = pair["f"] - pair["b"]
            te = float(active.std(ddof=1) * np.sqrt(TRADING_DAYS) * 100)
            vol = float(pair["f"].std(ddof=1) * np.sqrt(TRADING_DAYS) * 100)
            beta = _beta(pair["f"], pair["b"])[0]

    # ---- active share (look-through, over the union of stock + benchmark names) ----
    union = set(stock_w) | set(bench_w)
    active_share = 0.5 * sum(abs(active_w(t)) for t in union) * 100

    # ---- concentration of the STOCK sleeve (renormalized; the overlay is a
    # diversified index, so including it would overstate concentration) ----
    sv = np.array(list(stock_w.values()))
    ssum = sv.sum()
    svn = sv / ssum if ssum else sv
    hhi = float((svn ** 2).sum() * 10000) if svn.size else 0.0
    eff_n = float(1.0 / (svn ** 2).sum()) if svn.size else 0.0
    top5 = float(np.sort(sv)[::-1][:5].sum() * 100)  # actual % of fund in top-5 stocks

    # ---- active risk contribution (ex-ante a' Σ a over held stocks) ----
    cols = [t for t in stock_w if t in rets.columns]
    contrib: dict[str, float] = {}
    if cols:
        sig = (rets[cols].cov() * TRADING_DAYS).to_numpy()
        a = np.array([active_w(t) for t in cols])
        var = float(a @ sig @ a)
        if var > 0:
            mctr = (sig @ a) * a  # component contributions to a'Σa
            for t, c in zip(cols, mctr):
                contrib[t] = float(c / var)  # fraction of active variance

    rows = []
    for t in stock_w:
        rows.append({
            "t": t,
            "name": names.get(t, t),
            "port_w": round(stock_w[t] * 100, 2),
            "bench_w": round(bench_w.get(t, 0.0) * 100, 3),
            "active_w": round(active_w(t) * 100, 2),
            "risk_contrib": round(contrib.get(t, 0.0) * 100, 1),
        })
    rows.sort(key=lambda r: r["risk_contrib"], reverse=True)

    # ---- active sector tilts (look-through: stock tilts + overlay = benchmark) ----
    bench_grp = _bench_sector_groups(conn, bench)
    port_grp = {gname: overlay * bench_grp.get(gname, 0.0) for gname in UOIG_GROUPS}
    for t, w in stock_w.items():
        grp = _uoig_group(sectors.get(t))
        if grp:
            port_grp[grp] += w
    tilts = [{
        "group": gname,
        "port_w": round(port_grp[gname] * 100, 1),
        "bench_w": round(bench_grp.get(gname, 0.0) * 100, 1),
        "active": round((port_grp[gname] - bench_grp.get(gname, 0.0)) * 100, 1),
    } for gname in UOIG_GROUPS]

    return {
        "fund": fund_name,
        "benchmark": bench,
        "overlay": round(overlay * 100, 1),  # % of book in the benchmark ETF
        "kpis": {
            "tracking_error": round(te, 2) if te is not None else None,
            "active_share": round(active_share, 1),
            "beta": round(beta, 2) if beta is not None else None,
            "vol": round(vol, 1) if vol is not None else None,
        },
        "concentration": {
            "holdings": len(stock_w),  # number of individual stock picks
            "effective_n": round(eff_n, 1),
            "top5": round(top5, 1),
            "hhi": round(hhi),
        },
        "risk_contribution": rows,
        "sector_tilts": tilts,
    }


# ---------------------------------------------------------------------------
# Shared book/covariance extraction for the what-if sandbox and the optimizer.
# The heavy inputs (full price scan over remote Postgres) are cached in-process
# so iterating on optimizer views doesn't re-read the DB on every solve.
# ---------------------------------------------------------------------------
_BOOK_CACHE: dict[str, tuple[float, dict]] = {}
_RF_CACHE: list = [0.0, None]  # [timestamp, value]
_CACHE_TTL = 300  # seconds


def _book_cached(cfg: dict, conn: sqlite3.Connection, fund_name: str) -> dict:
    import time
    hit = _BOOK_CACHE.get(fund_name)
    now = time.time()
    if hit and (now - hit[0]) < _CACHE_TTL:
        return hit[1]
    b = _book(cfg, conn, fund_name)
    _BOOK_CACHE[fund_name] = (now, b)
    return b


def _risk_free(cfg: dict, conn: sqlite3.Connection) -> float:
    """Trailing-1Y return of the configured T-bill proxy (as api/build.py)."""
    import time
    from src.analytics.series import period_return, price_frame
    now = time.time()
    if _RF_CACHE[1] is not None and (now - _RF_CACHE[0]) < _CACHE_TTL:
        return _RF_CACHE[1]
    rf = period_return(price_frame(conn),
                       (cfg.get("risk") or {}).get("risk_free", "BIL"), "1Y") or 0.04
    _RF_CACHE[0], _RF_CACHE[1] = now, float(rf)
    return float(rf)


def _book(cfg: dict, conn: sqlite3.Connection, fund_name: str) -> dict:
    """One fund's book, split into tradable stocks / benchmark overlay / inert,
    plus an annualized eigen-clipped covariance over [stocks..., benchmark].

    Stocks are ordered by UOIG group then descending weight so the frontend's
    sliders and correlation heatmap show sector block structure. Held names
    without enough return history are 'inert' (treated as cash in the math)."""
    bench = next((f["benchmark"] for f in cfg["funds"] if f["name"] == fund_name), None)
    if bench is None:
        raise ValueError(f"unknown fund {fund_name!r}")

    years = (cfg.get("risk") or {}).get("beta_window_years", 3)
    rets = daily_returns_matrix(conn, years)

    pos = load_positions(cfg, conn)
    g = pos[(pos.fund == fund_name) & (pos.sec_type != "cash")].copy()
    names = {r.ticker: r.name for r in g.itertuples()}
    groups = {r.ticker: (_uoig_group(r.sector) or "Other") for r in g.itertuples()}
    invested_value = float(g["market_value"].sum())

    all_w = {r.ticker: float(r.port_w) for r in g.itertuples() if r.port_w == r.port_w}
    tot = sum(all_w.values()) or 1.0
    all_w = {t: w / tot for t, w in all_w.items()}
    stock_w = {r.ticker: all_w[r.ticker] for r in g.itertuples()
               if r.sec_type == "stock" and r.ticker in all_w}
    overlay = 1.0 - sum(stock_w.values())

    grp_rank = {gname: i for i, gname in enumerate(UOIG_GROUPS)}
    order = sorted(stock_w, key=lambda t: (grp_rank.get(groups.get(t), 99), -stock_w[t]))

    def _has_history(t):
        return t in rets.columns and int(rets[t].notna().sum()) >= 60

    tradable = [t for t in order if _has_history(t)]
    excluded = [t for t in order if not _has_history(t)]
    inert = sum(stock_w[t] for t in excluded)  # cash-like: no return model

    cols = tradable + [bench]
    cov = _ann_cov(rets, cols)

    bench_w = _bench_weights(conn, bench)
    return {
        "bench": bench, "rets": rets, "names": names, "groups": groups,
        "invested_value": invested_value, "stock_w": stock_w, "overlay": overlay,
        "tradable": tradable, "excluded": excluded, "inert": inert,
        "cov": cov, "bench_w": bench_w,
    }


def _ann_cov(rets: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """Annualized sample covariance over `cols`, symmetrized and eigen-clipped
    to PSD (pairwise-complete estimation can leave tiny negative eigenvalues)."""
    m = (rets[cols].cov() * TRADING_DAYS).to_numpy()
    m = np.nan_to_num(m, nan=0.0)
    m = (m + m.T) / 2.0
    vals, vecs = np.linalg.eigh(m)
    vals = np.clip(vals, 1e-8, None)
    return vecs @ np.diag(vals) @ vecs.T


def whatif_payload(cfg: dict, conn: sqlite3.Connection, fund_name: str) -> dict:
    """Everything the frontend needs to recompute ex-ante tracking error, active
    share, beta and vol live as sliders move — covariance ships to the client."""
    b = _book_cached(cfg, conn, fund_name)
    cov, tradable = b["cov"], b["tradable"]
    sd = np.sqrt(np.clip(np.diag(cov), 0, None))
    denom = np.outer(sd, sd)
    denom[denom == 0] = 1.0
    corr = cov / denom

    n = len(tradable)
    stocks = [{
        "t": t,
        "name": b["names"].get(t, t),
        "group": b["groups"].get(t, "Other"),
        "w": round(b["stock_w"][t], 6),
        "bench_w": round(b["bench_w"].get(t, 0.0), 6),
        "vol": round(float(sd[i]) * 100, 1),
    } for i, t in enumerate(tradable)]

    return {
        "fund": fund_name,
        "benchmark": b["bench"],
        "overlay": round(b["overlay"], 6),
        "inert": round(b["inert"], 6),
        "excluded": b["excluded"],
        "invested_value": round(b["invested_value"], 2),
        # sum of ALL constituent weights (equities only) — the client needs this
        # for the unheld-names term of active share, since dropped futures/cash
        # rows mean the published weights don't sum to exactly 1.
        "bench_total": round(sum(b["bench_w"].values()), 6),
        "stocks": stocks,
        # (n+1)x(n+1), stocks in listed order then the benchmark last
        "cov": [[round(float(cov[i][j]), 8) for j in range(n + 1)] for i in range(n + 1)],
        "corr": [[round(float(corr[i][j]), 2) for j in range(n)] for i in range(n)],
    }


# ---------------------------------------------------------------------------
# Black-Litterman + constrained mean-variance optimizer.
#
# Expected returns are benchmark-implied (CAPM: beta_i x ERP, in excess-of-rf
# space), then tilted by the club's views via the Black-Litterman posterior.
# The solver is projected gradient ascent onto the capped simplex (long-only,
# fully-invested stock sleeve, per-name cap) — exact projection by bisection,
# no external dependencies. The benchmark overlay sleeve is held constant and
# all reported stats are full-book (overlay included).
# ---------------------------------------------------------------------------
_CONF = {"low": 0.25, "med": 0.5, "high": 0.75}


def _project_capped_simplex(v: np.ndarray, cap: float) -> np.ndarray:
    """Euclidean projection onto {w: sum w = 1, 0 <= w <= cap} by bisecting the
    shift lambda in w = clip(v - lambda, 0, cap)."""
    lo, hi = float(v.min()) - 1.0, float(v.max())
    for _ in range(48):
        mid = (lo + hi) / 2.0
        if np.clip(v - mid, 0.0, cap).sum() > 1.0:
            lo = mid
        else:
            hi = mid
    return np.clip(v - (lo + hi) / 2.0, 0.0, cap)


def _solve_qp(a: np.ndarray, H: np.ndarray, cap: float,
              iters: int = 1500, tol: float = 1e-9) -> np.ndarray:
    """maximize a'w - 0.5 w'Hw over the capped simplex (H PSD).
    FISTA (accelerated projected gradient) with early stopping."""
    n = len(a)
    cap = max(cap, 1.0 / n + 1e-9)  # keep the feasible set non-empty
    L = float(np.linalg.eigvalsh(H).max()) + 1e-9
    step = 1.0 / L
    w = _project_capped_simplex(np.full(n, 1.0 / n), cap)
    z, tk = w.copy(), 1.0
    for _ in range(iters):
        w_new = _project_capped_simplex(z + step * (a - H @ z), cap)
        if float(np.abs(w_new - w).max()) < tol:
            return w_new
        t_new = (1.0 + np.sqrt(1.0 + 4.0 * tk * tk)) / 2.0
        z = w_new + ((tk - 1.0) / t_new) * (w_new - w)
        w, tk = w_new, t_new
    return w


def _bl_posterior(pi: np.ndarray, sigma: np.ndarray, views: list[dict],
                  tickers: list[str], erp: float, tau: float = 0.05) -> np.ndarray:
    """Black-Litterman posterior expected excess returns. Each view is
    {t, q, conf}: ticker t to outperform the benchmark by q (fraction/yr), so
    the view's absolute excess return is ERP + q. Omega is diagonal with
    variance scaled by confidence (Idzorek-style)."""
    idx = {t: i for i, t in enumerate(tickers)}
    rows = [(idx[v["t"]], erp + float(v["q"]), _CONF.get(v.get("conf", "med"), 0.5))
            for v in views if v.get("t") in idx]
    if not rows:
        return pi
    k, n = len(rows), len(pi)
    P = np.zeros((k, n))
    Q = np.zeros(k)
    omega = np.zeros(k)
    for r, (i, q, conf) in enumerate(rows):
        P[r, i] = 1.0
        Q[r] = q
        omega[r] = tau * sigma[i, i] * (1.0 / conf - 1.0) + 1e-12
    ts_inv = np.linalg.inv(tau * sigma + 1e-10 * np.eye(n))
    A = ts_inv + P.T @ np.diag(1.0 / omega) @ P
    bvec = ts_inv @ pi + P.T @ (Q / omega)
    return np.linalg.solve(A, bvec)


def solve_optimizer(cfg: dict, conn: sqlite3.Connection, fund_name: str,
                    views: list[dict] | None = None, max_pos: float = 0.10,
                    erp: float = 0.05) -> dict:
    """Constrained Black-Litterman mean-variance optimization of the stock
    sleeve (overlay fixed). Proposed portfolio = max-Sharpe on the constrained
    frontier. All stats are full-book and use the posterior returns for both
    the current and proposed book, so before/after is apples-to-apples."""
    b = _book_cached(cfg, conn, fund_name)
    tradable, cov = b["tradable"], b["cov"]
    n = len(tradable)
    if n < 2:
        raise ValueError("not enough tradable names to optimize")

    o, inert = b["overlay"], b["inert"]
    k = max(1.0 - o - inert, 1e-9)          # stock-sleeve fraction of the book
    sig_ss = cov[:n, :n]                     # stock block
    sig_sb = cov[:n, n]                      # stock x benchmark
    var_b = float(cov[n, n])

    rf = _risk_free(cfg, conn)

    # Implied excess returns (CAPM vs the fund's own benchmark), then BL tilt.
    betas = sig_sb / (var_b or 1.0)
    pi = betas * erp
    mu = _bl_posterior(pi, sig_ss, views or [], tradable, erp)

    # Full-book stats for sleeve weights s (fractions of the stock sleeve).
    def full_stats(s: np.ndarray) -> dict:
        wf = k * s                                     # full-book stock weights
        ret_x = float(wf @ mu) + o * erp               # excess return
        var = float(wf @ sig_ss @ wf + 2 * o * (wf @ sig_sb) + o * o * var_b)
        vol = float(np.sqrt(max(var, 0)))
        x_b = -(1.0 - o)                               # active coeff on benchmark
        te2 = float(wf @ sig_ss @ wf + 2 * x_b * (wf @ sig_sb) + x_b * x_b * var_b)
        te = float(np.sqrt(max(te2, 0)))
        beta = float((wf @ sig_sb + o * var_b) / (var_b or 1.0))
        sharpe = (ret_x / vol) if vol > 0 else 0.0
        return {"ret": round((rf + ret_x) * 100, 1), "vol": round(vol * 100, 1),
                "sharpe": round(sharpe, 2), "te": round(te * 100, 2),
                "beta": round(beta, 2), "_ret_x": ret_x, "_vol": vol}

    # QP in sleeve space: maximize k mu's - delta/2 [k^2 s'Sig s + 2ko s'sig_sb + ...]
    cap_sleeve = min(1.0, max_pos / k)
    # #132: _solve_qp silently raises an infeasible per-name cap to 1/n — compute
    # the ACTUAL cap enforced here and report it in the payload (in % of book),
    # so the reported cap can never contradict the proposed positions.
    cap_sleeve_eff = max(cap_sleeve, 1.0 / n + 1e-9)

    def solve_for(delta: float) -> np.ndarray:
        a = k * mu - delta * k * o * sig_sb
        H = delta * (k * k) * sig_ss
        return _solve_qp(a, H, cap_sleeve_eff)

    frontier, best = [], None
    for delta in np.geomspace(0.8, 60.0, 16):
        s = solve_for(float(delta))
        st = full_stats(s)
        frontier.append({"vol": st["vol"], "ret": st["ret"]})
        sharpe = st["_ret_x"] / st["_vol"] if st["_vol"] > 0 else 0.0
        if best is None or sharpe > best[0]:
            best = (sharpe, s, st)
    _, s_prop, st_prop = best

    # Min-variance (full-book) for the frontier chart's low end.
    s_mv = _solve_qp(-1.0 * k * o * sig_sb, (k * k) * sig_ss, cap_sleeve_eff)
    st_mv = full_stats(s_mv)

    s_cur = np.array([b["stock_w"][t] for t in tradable]) / k
    st_cur = full_stats(s_cur)

    view_by_t = {v["t"]: v for v in (views or [])}
    rows = []
    for i, t in enumerate(tradable):
        w_cur = k * float(s_cur[i]) * 100
        w_prop = k * float(s_prop[i]) * 100
        rows.append({
            "t": t, "name": b["names"].get(t, t), "group": b["groups"].get(t, "Other"),
            "w_cur": round(w_cur, 2), "w_prop": round(w_prop, 2),
            "delta": round(w_prop - w_cur, 2),
            "dollars": round((w_prop - w_cur) / 100 * b["invested_value"]),
            "implied": round(float(rf + pi[i]) * 100, 1),
            "posterior": round(float(rf + mu[i]) * 100, 1),
            "view": view_by_t.get(t, {}).get("q"),
            "conf": view_by_t.get(t, {}).get("conf"),
        })
    rows.sort(key=lambda r: -abs(r["delta"]))
    turnover = 0.5 * sum(abs(r["delta"]) for r in rows)

    def pub(st):
        return {kk: vv for kk, vv in st.items() if not kk.startswith("_")}

    return {
        "fund": fund_name, "benchmark": b["bench"],
        "rf": round(rf * 100, 2), "erp": round(erp * 100, 2),
        "cap": round(cap_sleeve_eff * k * 100, 1),  # effective per-name cap, % of book (#132)
        "cap_requested": round(max_pos * 100, 1),   # what the user asked for
        "overlay": round(o * 100, 1),
        "n_views": len([v for v in (views or []) if v.get("t") in set(tradable)]),
        "rows": rows,
        "stats": {"before": pub(st_cur), "after": pub(st_prop)},
        "frontier": sorted(frontier, key=lambda p: p["vol"]),
        "points": {"current": {"vol": st_cur["vol"], "ret": st_cur["ret"]},
                   "proposed": {"vol": st_prop["vol"], "ret": st_prop["ret"]},
                   "minvar": {"vol": st_mv["vol"], "ret": st_mv["ret"]}},
        "turnover": round(turnover, 1),
    }
