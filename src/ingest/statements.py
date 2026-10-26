"""Full financial statements, ratios and sell-side consensus from yfinance.

Powers the expanded Financials tab. `build_statements(ticker)` returns one
JSON-safe payload:

    statements  income / balance / cashflow, each with annual, quarterly and a
                computed trailing-twelve-month column
    ratios      margins, returns, leverage and cash conversion per period
    valuation   multiples and market cap from Yahoo's `info`
    consensus   estimates, revisions, surprises, price targets, rating trend and
                the broker upgrade/downgrade log
    currency    reporting vs trading currency (they differ for ADRs)

Unlike research.py, numbers stay raw (floats, not "$1.5B" strings) so the client
can switch units, YoY and common-size views without another round trip.

Every section is wrapped on its own: a missing statement or an uncovered name
degrades to a `partial` entry instead of failing the whole payload. Caching and
the HTTP route are layered on top of this module separately.
"""
from __future__ import annotations

import datetime as dt
import time

import pandas as pd

from src.ingest.providers import yf_ticker
from src.ingest.research import _num
from src.model import cache

_CACHE: dict[str, tuple[float, dict]] = {}   # unowned names, in-process
_TTL = 21600             # unowned: statements move quarterly, estimates slowly -> 6h
_SNAPSHOT_TTL = 2592000  # owned: 30-day grace; reads deliberately allow stale
_NS_LIVE, _NS_SNAPSHOT = "statements", "stock_statements"

# kind decides how a quarterly series rolls up to TTM:
#   flow   sum of the last four quarters
#   eps    sum of the last four quarters (per-share flow)
#   stock  latest quarter (balance-sheet items, share counts)
# level: 0 total/headline, 1 subtotal, 2 line item.
_INCOME = [
    ("revenue", "Total revenue", 0, "flow", ("Total Revenue", "Operating Revenue")),
    ("costOfRevenue", "Cost of revenue", 2, "flow", ("Cost Of Revenue", "Reconciled Cost Of Revenue")),
    ("grossProfit", "Gross profit", 1, "flow", ("Gross Profit",)),
    ("rnd", "Research and development", 2, "flow", ("Research And Development",)),
    ("sga", "Selling, general and administrative", 2, "flow", ("Selling General And Administration",)),
    ("opex", "Operating expense", 2, "flow", ("Operating Expense",)),
    ("operatingIncome", "Operating income", 1, "flow", ("Operating Income", "Total Operating Income As Reported")),
    # Banks report these instead of gross profit / operating income.
    ("netInterestIncome", "Net interest income", 1, "flow", ("Net Interest Income",)),
    ("interestIncome", "Interest income", 2, "flow", ("Interest Income",)),
    ("interestExpense", "Interest expense", 2, "flow", ("Interest Expense",)),
    ("nonInterestExpense", "Non-interest expense", 2, "flow", ("Other Non Interest Expense",)),
    ("pretaxIncome", "Pretax income", 1, "flow", ("Pretax Income",)),
    ("tax", "Tax provision", 2, "flow", ("Tax Provision",)),
    ("netIncome", "Net income", 0, "flow", ("Net Income", "Net Income Common Stockholders")),
    ("ebit", "EBIT", 1, "flow", ("EBIT",)),
    ("ebitda", "EBITDA", 1, "flow", ("EBITDA", "Normalized EBITDA")),
    ("dilutedEps", "Diluted EPS", 0, "eps", ("Diluted EPS", "Basic EPS")),
    ("dilutedShares", "Diluted shares", 2, "stock", ("Diluted Average Shares", "Basic Average Shares")),
]

_BALANCE = [
    ("cash", "Cash and short-term investments", 1, "stock", ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")),
    ("receivables", "Receivables", 2, "stock", ("Receivables", "Accounts Receivable")),
    ("inventory", "Inventory", 2, "stock", ("Inventory",)),
    ("currentAssets", "Total current assets", 1, "stock", ("Current Assets",)),
    ("ppe", "Net property, plant and equipment", 2, "stock", ("Net PPE",)),
    ("goodwill", "Goodwill", 2, "stock", ("Goodwill",)),
    ("totalAssets", "Total assets", 0, "stock", ("Total Assets",)),
    ("payables", "Accounts payable", 2, "stock", ("Accounts Payable", "Payables")),
    ("currentDebt", "Current debt", 2, "stock", ("Current Debt And Capital Lease Obligation", "Current Debt")),
    ("currentLiabilities", "Total current liabilities", 1, "stock", ("Current Liabilities",)),
    ("longTermDebt", "Long-term debt", 2, "stock", ("Long Term Debt And Capital Lease Obligation", "Long Term Debt")),
    ("totalLiabilities", "Total liabilities", 0, "stock", ("Total Liabilities Net Minority Interest",)),
    ("equity", "Stockholders' equity", 0, "stock", ("Stockholders Equity", "Common Stock Equity")),
    ("totalDebt", "Total debt", 1, "stock", ("Total Debt",)),
    ("netDebt", "Net debt", 1, "stock", ("Net Debt",)),
    ("workingCapital", "Working capital", 1, "stock", ("Working Capital",)),
    ("investedCapital", "Invested capital", 1, "stock", ("Invested Capital",)),
    ("tangibleBook", "Tangible book value", 1, "stock", ("Tangible Book Value",)),
    ("sharesOutstanding", "Shares outstanding", 2, "stock", ("Ordinary Shares Number", "Share Issued")),
]

_CASHFLOW = [
    ("operatingCf", "Operating cash flow", 0, "flow", ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities")),
    ("cfNetIncome", "Net income", 2, "flow", ("Net Income From Continuing Operations",)),
    ("da", "Depreciation and amortization", 2, "flow", ("Depreciation And Amortization", "Depreciation Amortization Depletion")),
    ("sbc", "Stock-based compensation", 2, "flow", ("Stock Based Compensation",)),
    ("deferredTax", "Deferred tax", 2, "flow", ("Deferred Tax", "Deferred Income Tax")),
    ("workingCapitalChange", "Change in working capital", 2, "flow", ("Change In Working Capital",)),
    ("investingCf", "Investing cash flow", 0, "flow", ("Investing Cash Flow",)),
    ("capex", "Capital expenditure", 2, "flow", ("Capital Expenditure",)),
    ("acquisitions", "Acquisitions", 2, "flow", ("Net Business Purchase And Sale", "Purchase Of Business")),
    ("investmentsNet", "Net investment purchases", 2, "flow", ("Net Investment Purchase And Sale",)),
    ("financingCf", "Financing cash flow", 0, "flow", ("Financing Cash Flow",)),
    ("dividends", "Dividends paid", 2, "flow", ("Cash Dividends Paid", "Common Stock Dividend Paid")),
    ("buybacks", "Share repurchases", 2, "flow", ("Repurchase Of Capital Stock", "Common Stock Payments")),
    ("netDebtIssuance", "Net debt issued", 2, "flow", ("Net Issuance Payments Of Debt",)),
    ("fcf", "Free cash flow", 0, "flow", ("Free Cash Flow",)),
    ("changeInCash", "Change in cash", 1, "flow", ("Changes In Cash",)),
    ("endCash", "Ending cash", 1, "stock", ("End Cash Position",)),
]

_STATEMENTS = {
    "income": (_INCOME, "income_stmt", "quarterly_income_stmt"),
    "balance": (_BALANCE, "balance_sheet", "quarterly_balance_sheet"),
    "cashflow": (_CASHFLOW, "cashflow", "quarterly_cashflow"),
}

# Tax-rate bounds for NOPAT; Yahoo's provision/pretax ratio is noisy around
# one-offs, so clamp rather than let a negative rate inflate ROIC.
_TAX_MIN, _TAX_MAX = 0.0, 0.40


# ---------- helpers ----------
def _frame(tk, attr):
    try:
        df = getattr(tk, attr)
    except Exception:
        return None
    if df is None or getattr(df, "empty", True):
        return None
    try:
        # newest -> oldest regardless of how Yahoo ordered the columns
        return df.reindex(sorted(df.columns, key=pd.Timestamp, reverse=True), axis=1)
    except Exception:
        return df


def _pick(series, names):
    """First non-null value among Yahoo aliases for one line item, else None."""
    if series is None:
        return None
    for n in names:
        if n in series.index:
            v = _num(series[n])
            if v is not None:
                return v
    return None


def _iso(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def _fy_end_month(annual) -> int:
    """Fiscal year-end month, read from the newest annual column (default Dec)."""
    if annual is not None and len(annual.columns):
        return pd.Timestamp(annual.columns[0]).month
    return 12


def _fy_year(ts, fye_month: int) -> int:
    d = pd.Timestamp(ts)
    return d.year + 1 if d.month > fye_month else d.year


def _fq(ts, fye_month: int) -> int:
    """Fiscal quarter (1-4) of a quarter-end date."""
    return ((pd.Timestamp(ts).month - fye_month - 1) % 12) // 3 + 1


def _annual_label(ts, fye_month: int) -> str:
    return f"FY{_fy_year(ts, fye_month)}"


def _quarter_label(ts, fye_month: int) -> str:
    return f"Q{_fq(ts, fye_month)} FY{str(_fy_year(ts, fye_month))[2:]}"


# ---------- statements ----------
def _complete_cols(df) -> list:
    """Columns that carry a real quarter of data, newest first.

    Yahoo sometimes appends a just-reported quarter holding only EPS (JPM did).
    Rolling that into TTM would drop every row, so TTM anchors on the newest
    columns with at least half the populated rows of the fullest column.
    """
    counts = df.notna().sum()
    floor = counts.max() / 2
    return [c for c in df.columns if counts[c] >= floor]


def _ttm_series(quarterly, spec):
    """Synthesise (series, end date) for TTM from the last four full quarters.

    Yahoo's own ttm_* frames carried stale dates for some names, so we roll it up
    ourselves. A row needs all four quarters; a partial sum would understate it.
    """
    if quarterly is None:
        return None, None
    full = _complete_cols(quarterly)
    if len(full) < 4:
        return None, None
    last4 = [quarterly[c] for c in full[:4]]
    out = {}
    for _key, _label, _lvl, kind, names in spec:
        vals = [_pick(s, names) for s in last4]
        if kind == "stock":
            v = vals[0]
        elif any(x is None for x in vals):
            continue
        else:
            v = sum(vals)
        if v is not None:
            out[names[0]] = v
    return (pd.Series(out), full[0]) if out else (None, None)


def _rows(spec, columns):
    """Build the display rows for a list of column Series (None entries allowed).

    Rows with no data in any column are dropped, which is also what makes banks
    work without a separate layout: gross profit simply never appears.
    """
    rows = []
    for key, label, level, kind, names in spec:
        vals = [_pick(c, names) for c in columns]
        if all(v is None for v in vals):
            continue
        rows.append({"key": key, "label": label, "level": level, "kind": kind, "vals": vals})
    return rows


def _other_rows(df, spec, limit_cols):
    """Yahoo line items we didn't map, so the UI can offer them under 'Other'."""
    mapped = {n for *_, names in spec for n in names}
    cols = list(df.columns[:limit_cols])
    rows = []
    for name in df.index:
        if name in mapped:
            continue
        vals = [_num(df.at[name, c]) for c in cols]
        if all(v is None for v in vals):
            continue
        rows.append({"key": name, "label": name, "level": 2, "kind": "flow", "vals": vals})
    return rows


def _statement(spec, annual, quarterly, fye):
    block = {}
    if annual is not None:
        cols = list(annual.columns)
        block["annual"] = {
            "periods": [_annual_label(c, fye) for c in cols],
            "ends": [_iso(c) for c in cols],
            "rows": _rows(spec, [annual[c] for c in cols]),
            "other": _other_rows(annual, spec, len(cols)),
        }
    if quarterly is not None:
        cols = list(quarterly.columns)
        block["quarterly"] = {
            "periods": [_quarter_label(c, fye) for c in cols],
            "ends": [_iso(c) for c in cols],
            "rows": _rows(spec, [quarterly[c] for c in cols]),
            "other": _other_rows(quarterly, spec, len(cols)),
        }
        ttm, ttm_end = _ttm_series(quarterly, spec)
        if ttm is not None:
            block["ttm"] = {
                "period": f"TTM {pd.Timestamp(ttm_end).strftime('%b-%y')}",
                "end": _iso(ttm_end),
                "vals": {r["key"]: r["vals"][0] for r in _rows(spec, [ttm])},
            }
    return block


def _is_bank(income) -> bool:
    """Banks report net interest income and no gross profit / operating income."""
    if income is None:
        return False
    first = income[income.columns[0]]
    return (_pick(first, ("Net Interest Income",)) is not None
            and _pick(first, ("Gross Profit",)) is None
            and _pick(first, ("Operating Income",)) is None)


# ---------- ratios ----------
def _ratio_set(inc, bal, cf, prior_bal=None, returns=True, bank=False):
    """Ratios for one period from raw Yahoo Series (any may be None)."""
    g = lambda s, key, spec: _pick(s, next(n for k, *_x, n in spec if k == key))  # noqa: E731
    rev = g(inc, "revenue", _INCOME)
    gp = g(inc, "grossProfit", _INCOME)
    oi = g(inc, "operatingIncome", _INCOME)
    ni = g(inc, "netIncome", _INCOME)
    ebitda = g(inc, "ebitda", _INCOME)
    ebit = g(inc, "ebit", _INCOME)
    intexp = g(inc, "interestExpense", _INCOME)
    pretax = g(inc, "pretaxIncome", _INCOME)
    tax = g(inc, "tax", _INCOME)
    fcf = g(cf, "fcf", _CASHFLOW)
    capex = g(cf, "capex", _CASHFLOW)
    divs = g(cf, "dividends", _CASHFLOW)
    buys = g(cf, "buybacks", _CASHFLOW)
    assets = g(bal, "totalAssets", _BALANCE)
    equity = g(bal, "equity", _BALANCE)
    curA = g(bal, "currentAssets", _BALANCE)
    curL = g(bal, "currentLiabilities", _BALANCE)
    debt = g(bal, "totalDebt", _BALANCE)
    netdebt = g(bal, "netDebt", _BALANCE)
    # Debt + equity, not Yahoo's "Invested Capital": that row dropped equity in
    # several ASML quarters, which blew ROIC up to 600%.
    invcap = (debt + equity) if (debt is not None and equity is not None) else None
    shares = g(bal, "sharesOutstanding", _BALANCE)

    tax_rate = _div(tax, pretax)
    nopat = None
    if oi is not None and tax_rate is not None:
        nopat = oi * (1 - min(max(tax_rate, _TAX_MIN), _TAX_MAX))

    out = {
        "grossMargin": _div(gp, rev),
        "operatingMargin": _div(oi, rev),
        "ebitdaMargin": _div(ebitda, rev),
        "netMargin": _div(ni, rev),
        "fcfMargin": _div(fcf, rev),
        "capexPctRevenue": _div(abs(capex) if capex is not None else None, rev),
        "fcfConversion": _div(fcf, ni),
        "currentRatio": _div(curA, curL),
        "debtToEquity": _div(debt, equity),
        "netDebtToEbitda": _div(netdebt, ebitda),
        "interestCoverage": _div(ebit if ebit is not None else oi, abs(intexp) if intexp else None),
        "shareholderReturnOfFcf": _div(
            (abs(divs or 0) + abs(buys or 0)) if (divs is not None or buys is not None) else None, fcf),
    }
    if returns:
        # Ending balances, not averages: consistent across annual and TTM and
        # robust to a missing prior period.
        out["roe"] = _div(ni, equity)
        out["roa"] = _div(ni, assets)
        out["roic"] = _div(nopat, invcap)
    if bank:
        # Cash-flow and working-capital ratios don't describe a bank: its
        # operating cash flow is dominated by deposits and trading balances.
        for k in ("fcfMargin", "fcfConversion", "capexPctRevenue", "currentRatio",
                  "netDebtToEbitda", "shareholderReturnOfFcf", "roic", "interestCoverage"):
            out.pop(k, None)
    prior_shares = g(prior_bal, "sharesOutstanding", _BALANCE) if prior_bal is not None else None
    out["sharesChange"] = (shares / prior_shares - 1) if (shares and prior_shares) else None
    return out


_RATIO_META = [
    ("grossMargin", "Gross margin", "pct"), ("operatingMargin", "Operating margin", "pct"),
    ("ebitdaMargin", "EBITDA margin", "pct"), ("netMargin", "Net margin", "pct"),
    ("fcfMargin", "FCF margin", "pct"), ("roe", "Return on equity", "pct"),
    ("roa", "Return on assets", "pct"), ("roic", "Return on invested capital", "pct"),
    ("currentRatio", "Current ratio", "x"), ("debtToEquity", "Debt / equity", "x"),
    ("netDebtToEbitda", "Net debt / EBITDA", "x"), ("interestCoverage", "Interest coverage", "x"),
    ("fcfConversion", "FCF / net income", "x"), ("capexPctRevenue", "Capex % of revenue", "pct"),
    ("shareholderReturnOfFcf", "Dividends + buybacks % of FCF", "pct"),
    ("sharesChange", "Share count change", "pct"),
]


def _ratio_block(sets, periods, ends):
    rows = []
    for key, label, fmt in _RATIO_META:
        vals = [s.get(key) for s in sets]
        if all(v is None for v in vals):
            continue
        rows.append({"key": key, "label": label, "fmt": fmt, "vals": vals})
    return {"periods": periods, "ends": ends, "rows": rows}


def _ratios(frames, fye, bank=False):
    inc_a, bal_a, cf_a, inc_q, bal_q, cf_q = frames

    def col(df, c):
        return df[c] if (df is not None and c in df.columns) else None

    out = {}
    if inc_a is not None:
        cols = list(inc_a.columns)
        sets = []
        for i, c in enumerate(cols):
            prior = col(bal_a, cols[i + 1]) if i + 1 < len(cols) else None
            sets.append(_ratio_set(inc_a[c], col(bal_a, c), col(cf_a, c), prior, bank=bank))
        out["annual"] = _ratio_block(sets, [_annual_label(c, fye) for c in cols], [_iso(c) for c in cols])
    if inc_q is not None:
        cols = list(inc_q.columns)
        sets = []
        for i, c in enumerate(cols):
            prior = col(bal_q, cols[i + 4]) if i + 4 < len(cols) else None
            # Single-quarter return ratios aren't comparable to annual ones.
            sets.append(_ratio_set(inc_q[c], col(bal_q, c), col(cf_q, c), prior, returns=False, bank=bank))
        out["quarterly"] = _ratio_block(sets, [_quarter_label(c, fye) for c in cols], [_iso(c) for c in cols])
        ttm_inc, ttm_end = _ttm_series(inc_q, _INCOME)
        ttm_cf, _ = _ttm_series(cf_q, _CASHFLOW)
        bal_latest = None
        if bal_q is not None:
            # Balance sheet as of the TTM end when Yahoo has it, else its newest full column.
            bal_latest = col(bal_q, ttm_end)
            if bal_latest is None and _complete_cols(bal_q):
                bal_latest = bal_q[_complete_cols(bal_q)[0]]
        if ttm_inc is not None:
            ttm = _ratio_set(ttm_inc, bal_latest, ttm_cf, bank=bank)
            out["ttm"] = {"period": f"TTM {pd.Timestamp(ttm_end).strftime('%b-%y')}",
                          "vals": {k: v for k, v in ttm.items() if v is not None}}
    return out


# ---------- valuation / currency ----------
_VALUATION = [
    ("marketCap", "marketCap"), ("enterpriseValue", "enterpriseValue"),
    ("trailingPE", "trailingPE"), ("forwardPE", "forwardPE"),
    ("priceToSales", "priceToSalesTrailing12Months"), ("priceToBook", "priceToBook"),
    ("evToEbitda", "enterpriseToEbitda"), ("evToRevenue", "enterpriseToRevenue"),
    ("peg", "trailingPegRatio"), ("dividendYield", "dividendYield"), ("beta", "beta"),  # yield is already in percent
]


def _info(tk) -> dict:
    try:
        return tk.info or {}
    except Exception:
        return {}


# Yahoo divides a USD price by EUR/JPY financials for ADRs and foreign listings,
# so these come back off by orders of magnitude when the currencies differ.
_CURRENCY_SENSITIVE = {"enterpriseValue", "priceToBook", "evToEbitda", "evToRevenue"}


def _valuation(info: dict):
    out = {k: _num(info.get(src)) for k, src in _VALUATION}
    rep_c, trade_c = info.get("financialCurrency"), info.get("currency")
    if rep_c and trade_c and rep_c != trade_c:
        out = {k: v for k, v in out.items() if k not in _CURRENCY_SENSITIVE}
    out = {k: v for k, v in out.items() if v is not None}
    return out or None


def _currency(info: dict):
    reporting, trading = info.get("financialCurrency"), info.get("currency")
    if not (reporting or trading):
        return None
    return {"reporting": reporting, "trading": trading}


# ---------- consensus ----------
def _next_quarter_end(ts) -> pd.Timestamp:
    return pd.Timestamp(ts) + pd.DateOffset(months=3) + pd.offsets.MonthEnd(0)


def _estimate_labels(annual, quarterly, fye):
    """Map Yahoo's 0q/+1q/0y/+1y keys to real fiscal period labels."""
    labels = {}
    if annual is not None and len(annual.columns):
        y = _fy_year(annual.columns[0], fye)
        labels["0y"], labels["+1y"] = f"FY{y + 1}E", f"FY{y + 2}E"
    if quarterly is not None and len(quarterly.columns):
        q0 = _next_quarter_end(quarterly.columns[0])
        q1 = _next_quarter_end(q0)
        labels["0q"], labels["+1q"] = _quarter_label(q0, fye) + "E", _quarter_label(q1, fye) + "E"
    return labels


def _estimates(tk, labels):
    ee, re = getattr(tk, "earnings_estimate", None), getattr(tk, "revenue_estimate", None)
    rows = []
    for key in ("0q", "+1q", "0y", "+1y"):
        e = ee.loc[key] if (ee is not None and key in ee.index) else None
        r = re.loc[key] if (re is not None and key in re.index) else None
        if e is None and r is None:
            continue
        g = lambda s, f: _num(s.get(f)) if s is not None else None  # noqa: E731
        n = g(e, "numberOfAnalysts")
        rows.append({
            "key": key, "period": labels.get(key, key),
            "eps": {"avg": g(e, "avg"), "low": g(e, "low"), "high": g(e, "high"),
                    "yearAgo": g(e, "yearAgoEps"), "growth": g(e, "growth")},
            "revenue": {"avg": g(r, "avg"), "low": g(r, "low"), "high": g(r, "high"),
                        "yearAgo": g(r, "yearAgoRevenue"),
                        "growth": g(r, "growth")},
            "analysts": int(n) if n is not None else None,
            "currency": (e.get("currency") if e is not None else None) or (r.get("currency") if r is not None else None),
        })
    return rows


def _revisions(tk, labels):
    df = getattr(tk, "eps_trend", None)
    if df is None or df.empty:
        return []
    rows = []
    for key in df.index:
        s = df.loc[key]
        rows.append({"key": key, "period": labels.get(key, key),
                     "current": _num(s.get("current")), "d7": _num(s.get("7daysAgo")),
                     "d30": _num(s.get("30daysAgo")), "d60": _num(s.get("60daysAgo")),
                     "d90": _num(s.get("90daysAgo"))})
    return rows


def _surprises(tk, fye):
    df = getattr(tk, "earnings_history", None)
    if df is None or df.empty:
        return []
    rows = []
    for ts in df.index:
        s = df.loc[ts]
        pct = _num(s.get("surprisePercent"))
        rows.append({"period": _quarter_label(ts, fye), "end": _iso(ts),
                     "actual": _num(s.get("epsActual")), "estimate": _num(s.get("epsEstimate")),
                     "difference": _num(s.get("epsDifference")),
                     # Yahoo returns a fraction (0.04 = 4%); expose it the same way.
                     "surprisePct": pct})
    return sorted(rows, key=lambda r: r["end"])


def _growth(tk, labels):
    df = getattr(tk, "growth_estimates", None)
    if df is None or df.empty:
        return []
    names = {**labels, "LTG": "Long-term"}
    return [{"key": k, "period": names.get(k, k),
             "stock": _num(df.loc[k].get("stockTrend")), "index": _num(df.loc[k].get("indexTrend"))}
            for k in df.index]


def _targets(tk):
    try:
        pt = tk.analyst_price_targets or {}
    except Exception:
        return None
    out = {k: _num(pt.get(k)) for k in ("current", "low", "mean", "median", "high")}
    return out if any(v is not None for v in out.values()) else None


def _rating_trend(tk):
    df = getattr(tk, "recommendations_summary", None)
    if df is None or df.empty:
        return []
    rows = []
    for _i, r in df.iterrows():
        counts = {k: int(_num(r.get(k)) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
        rows.append({"period": str(r.get("period")), **counts, "total": sum(counts.values())})
    return rows


def _broker_log(tk, limit):
    df = getattr(tk, "upgrades_downgrades", None)
    if df is None or df.empty:
        return []
    rows = []
    for ts, r in df.sort_index(ascending=False).head(limit).iterrows():
        tgt, prior = _num(r.get("currentPriceTarget")), _num(r.get("priorPriceTarget"))
        rows.append({
            "date": _iso(ts), "firm": r.get("Firm") or None,
            "to": r.get("ToGrade") or None, "from": r.get("FromGrade") or None,
            "action": r.get("Action") or None,
            "targetAction": r.get("priceTargetAction") or None,
            # Yahoo uses 0 for "no target"; surface that as null.
            "target": tgt or None, "priorTarget": prior or None,
        })
    return rows


def _consensus(tk, annual, quarterly, fye, broker_limit):
    labels = _estimate_labels(annual, quarterly, fye)
    parts = {
        "estimates": lambda: _estimates(tk, labels),
        "revisions": lambda: _revisions(tk, labels),
        "surprises": lambda: _surprises(tk, fye),
        "growth": lambda: _growth(tk, labels),
        "targets": lambda: _targets(tk),
        "ratingTrend": lambda: _rating_trend(tk),
        "brokerLog": lambda: _broker_log(tk, broker_limit),
    }
    out, failed = {}, []
    for name, fn in parts.items():
        try:
            out[name] = fn()
        except Exception:
            out[name], failed = ([] if name != "targets" else None), failed + [f"consensus.{name}"]
    has = any(out[k] for k in out)
    return (out if has else None), failed


# ---------- public ----------
def has_data(payload: dict) -> bool:
    """True when at least one section resolved (an all-empty result is an upstream
    failure and must not be cached over a good one)."""
    return bool(payload.get("statements") or payload.get("consensus") or payload.get("valuation"))


def build_statements(ticker: str, tk=None, *, broker_limit: int = 100) -> dict:
    """Assemble the Financials-tab payload for one ticker (live yfinance calls)."""
    tk = tk or yf_ticker(ticker)
    partial: list[str] = []

    frames, statements = {}, {}
    for name, (_spec, a_attr, q_attr) in _STATEMENTS.items():
        frames[name] = (_frame(tk, a_attr), _frame(tk, q_attr))

    fye = _fy_end_month(next((a for a, _ in frames.values() if a is not None), None))
    annual_ref = next((a for a, _ in frames.values() if a is not None), None)
    quarterly_ref = next((q for _, q in frames.values() if q is not None), None)

    for name, (spec, _a, _q) in _STATEMENTS.items():
        annual, quarterly = frames[name]
        if annual is None and quarterly is None:
            partial.append(f"statements.{name}")
            continue
        if annual is None:
            partial.append(f"statements.{name}.annual")
        if quarterly is None:
            partial.append(f"statements.{name}.quarterly")
        try:
            statements[name] = _statement(spec, annual, quarterly, fye)
        except Exception:
            partial.append(f"statements.{name}")

    bank = _is_bank(frames["income"][0] if frames["income"][0] is not None else frames["income"][1])
    ratios = None
    try:
        ratios = _ratios((frames["income"][0], frames["balance"][0], frames["cashflow"][0],
                          frames["income"][1], frames["balance"][1], frames["cashflow"][1]), fye, bank) or None
    except Exception:
        partial.append("ratios")

    info = _info(tk)
    if not info:
        partial.append("valuation")

    consensus, failed = _consensus(tk, annual_ref, quarterly_ref, fye, broker_limit)
    partial += failed
    if consensus is None:
        partial.append("consensus")

    return {
        "ticker": ticker.upper(),
        "fiscalYearEndMonth": fye if annual_ref is not None else None,
        "isBank": bank,
        "currency": _currency(info),
        "statements": statements or None,
        "ratios": ratios,
        "valuation": _valuation(info),
        "consensus": consensus,
        "partial": sorted(set(partial)),
        "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


# ---------- cached access ----------
def refresh_statements_snapshot(ticker: str) -> dict:
    """Nightly refresh for a current holding's statements, last-known-good.

    An all-empty response is an upstream failure and never overwrites the prior
    snapshot.
    """
    t = ticker.upper()
    payload = build_statements(t)
    if has_data(payload):
        cache.set(_NS_SNAPSHOT, t, payload, _SNAPSHOT_TTL)
    return payload


def statements_snapshot(ticker: str) -> dict:
    """Read a holding's snapshot without ever contacting yfinance."""
    t = ticker.upper()
    cached = cache.peek(_NS_SNAPSHOT, t)
    if cached is not cache.MISS:
        value, _age = cached
        return {**value, "ticker": t, "snapshotPending": False}
    return {"ticker": t, "statements": None, "ratios": None, "valuation": None,
            "consensus": None, "currency": None, "isBank": False, "partial": [],
            "fetchedAt": None, "snapshotPending": True}


def stock_statements(ticker: str) -> dict:
    """On-demand payload for a ticker that is not currently owned."""
    t = ticker.upper()
    now = time.time()
    hit = _CACHE.get(t)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    cached = cache.get(_NS_LIVE, t)
    if cached is not cache.MISS:
        value, age = cached
        _CACHE[t] = (now - age, value)
        return value

    payload = build_statements(t)
    if not has_data(payload):
        # Don't cache a failed fetch over good data; serve the last copy if any.
        stale = cache.peek(_NS_LIVE, t)
        if stale is not cache.MISS:
            return {**stale[0], "ticker": t, "stale": True}
        return payload
    _CACHE[t] = (now, payload)
    cache.set(_NS_LIVE, t, payload, _TTL)
    return payload
