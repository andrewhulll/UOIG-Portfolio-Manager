"""Live equity screener over the full market (Yahoo's EquityQuery / screen API).

Unlike ``src/ingest/lookup.py`` (which looks up one ticker at a time), this
searches *every* equity Yahoo indexes by fundamental, valuation, technical and
ESG criteria — the tool analysts use to find names we don't already own.

Two public helpers:
  screener_fields()                 -> the filterable field catalog (drives the UI)
  run_screen(filters, sort, ...)    -> {total, rows} of matching quotes
"""
from __future__ import annotations

import hashlib
import json
import time

import yfinance as yf
from yfinance import EquityQuery

from src.ingest.providers import yf_retry, yf_session
from src.model import cache

_TTL = 180  # seconds — screener results move with the market; keep this short
_RESULTS_CACHE: dict[str, tuple[float, dict]] = {}

# US exchange codes yfinance/Yahoo recognizes (region=us).
EXCHANGES = [
    "ASE", "BTS", "CXI", "NAE", "NCM", "NGM", "NMS", "NYQ", "OEM", "OQB", "OQX",
    "PCX", "PNK", "YHD",
]

INDUSTRIES_BY_SECTOR = {
    "Basic Materials": [
        "Agricultural Inputs", "Aluminum", "Building Materials", "Chemicals",
        "Coking Coal", "Copper", "Gold", "Lumber & Wood Production",
        "Other Industrial Metals & Mining", "Other Precious Metals & Mining",
        "Paper & Paper Products", "Silver", "Specialty Chemicals", "Steel",
    ],
    "Communication Services": [
        "Advertising Agencies", "Broadcasting", "Electronic Gaming & Multimedia",
        "Entertainment", "Internet Content & Information", "Publishing",
        "Telecom Services",
    ],
    "Consumer Cyclical": [
        "Apparel Manufacturing", "Apparel Retail", "Auto & Truck Dealerships",
        "Auto Manufacturers", "Auto Parts", "Department Stores",
        "Footwear & Accessories", "Furnishings, Fixtures & Appliances", "Gambling",
        "Home Improvement Retail", "Internet Retail", "Leisure", "Lodging",
        "Luxury Goods", "Packaging & Containers", "Personal Services",
        "Recreational Vehicles", "Residential Construction", "Resorts & Casinos",
        "Restaurants", "Specialty Retail", "Textile Manufacturing", "Travel Services",
    ],
    "Consumer Defensive": [
        "Beverages—Brewers", "Beverages—Non-Alcoholic", "Beverages—Wineries & Distilleries",
        "Confectioners", "Discount Stores", "Education & Training Services",
        "Farm Products", "Food Distribution", "Grocery Stores",
        "Household & Personal Products", "Packaged Foods", "Tobacco",
    ],
    "Energy": [
        "Oil & Gas Drilling", "Oil & Gas E&P", "Oil & Gas Equipment & Services",
        "Oil & Gas Integrated", "Oil & Gas Midstream", "Oil & Gas Refining & Marketing",
        "Thermal Coal", "Uranium",
    ],
    "Financial Services": [
        "Asset Management", "Banks—Diversified", "Banks—Regional", "Capital Markets",
        "Credit Services", "Financial Conglomerates", "Financial Data & Stock Exchanges",
        "Insurance Brokers", "Insurance—Diversified", "Insurance—Life",
        "Insurance—Property & Casualty", "Insurance—Reinsurance", "Insurance—Specialty",
        "Mortgage Finance", "Shell Companies",
    ],
    "Healthcare": [
        "Biotechnology", "Diagnostics & Research", "Drug Manufacturers—General",
        "Drug Manufacturers—Specialty & Generic", "Health Information Services",
        "Healthcare Plans", "Medical Care Facilities", "Medical Devices",
        "Medical Distribution", "Medical Instruments & Supplies", "Pharmaceutical Retailers",
    ],
    "Industrials": [
        "Aerospace & Defense", "Airlines", "Airports & Air Services",
        "Building Products & Equipment", "Business Equipment & Supplies", "Conglomerates",
        "Consulting Services", "Electrical Equipment & Parts", "Engineering & Construction",
        "Farm & Heavy Construction Machinery", "Industrial Distribution",
        "Infrastructure Operations", "Integrated Freight & Logistics", "Marine Shipping",
        "Metal Fabrication", "Pollution & Treatment Controls", "Railroads",
        "Rental & Leasing Services", "Security & Protection Services",
        "Specialty Business Services", "Specialty Industrial Machinery",
        "Staffing & Employment Services", "Tools & Accessories", "Trucking",
        "Waste Management",
    ],
    "Real Estate": [
        "REIT—Diversified", "REIT—Healthcare Facilities", "REIT—Hotel & Motel",
        "REIT—Industrial", "REIT—Mortgage", "REIT—Office", "REIT—Residential",
        "REIT—Retail", "REIT—Specialty", "Real Estate Services",
        "Real Estate—Development", "Real Estate—Diversified",
    ],
    "Technology": [
        "Communication Equipment", "Computer Hardware", "Consumer Electronics",
        "Electronic Components", "Electronics & Computer Distribution",
        "Information Technology Services", "Scientific & Technical Instruments",
        "Semiconductor Equipment & Materials", "Semiconductors", "Software—Application",
        "Software—Infrastructure", "Solar",
    ],
    "Utilities": [
        "Utilities—Diversified", "Utilities—Independent Power Producers",
        "Utilities—Regulated Electric", "Utilities—Regulated Gas",
        "Utilities—Regulated Water", "Utilities—Renewable",
    ],
}
SECTORS = list(INDUSTRIES_BY_SECTOR.keys())
INDUSTRIES = sorted({i for group in INDUSTRIES_BY_SECTOR.values() for i in group})

PEER_GROUPS = [
    "Aerospace & Defense", "Auto Components", "Automobiles", "Banks",
    "Building Products", "Chemicals", "Commercial Services",
    "Construction & Engineering", "Construction Materials", "Consumer Durables",
    "Consumer Services", "Containers & Packaging", "Diversified Financials",
    "Diversified Metals", "Electrical Equipment", "Energy Services",
    "Food Products", "Food Retailers", "Healthcare", "Homebuilders",
    "Household Products", "Industrial Conglomerates", "Insurance", "Machinery",
    "Media", "Oil & Gas Producers", "Paper & Forestry", "Pharmaceuticals",
    "Precious Metals", "Real Estate", "Refiners & Pipelines", "Retailing",
    "Semiconductors", "Software & Services", "Steel", "Technology Hardware",
    "Telecommunication Services", "Textiles & Apparel", "Traders & Distributors",
    "Transportation", "Transportation Infrastructure", "Utilities",
]

# The filterable field catalog. `kind` drives the UI/validation:
#   "multi"  -> operator "is-in", value is a list of strings (from `values`)
#   "range"  -> operator gt/gte/lt/lte/btwn, value(s) numeric
FIELD_CATALOG = [
    # ---- company ----
    {"key": "sector", "label": "Sector", "category": "Company", "kind": "multi", "values": SECTORS},
    {"key": "industry", "label": "Industry", "category": "Company", "kind": "multi", "values": INDUSTRIES},
    {"key": "exchange", "label": "Exchange", "category": "Company", "kind": "multi", "values": EXCHANGES},
    {"key": "peer_group", "label": "Peer Group", "category": "Company", "kind": "multi", "values": PEER_GROUPS},

    # ---- price & trading ----
    {"key": "intradayprice", "label": "Price", "category": "Price & Trading", "kind": "range", "unit": "$"},
    {"key": "intradaymarketcap", "label": "Market Cap", "category": "Price & Trading", "kind": "range", "unit": "$"},
    {"key": "percentchange", "label": "Day Change", "category": "Price & Trading", "kind": "range", "unit": "%"},
    {"key": "fiftytwowkpercentchange", "label": "52-Week Change", "category": "Price & Trading", "kind": "range", "unit": "%"},
    {"key": "dayvolume", "label": "Day Volume", "category": "Price & Trading", "kind": "range"},
    {"key": "avgdailyvol3m", "label": "Avg Daily Volume (3M)", "category": "Price & Trading", "kind": "range"},
    {"key": "beta", "label": "Beta", "category": "Price & Trading", "kind": "range"},
    {"key": "pctheldinsider", "label": "% Held by Insiders", "category": "Price & Trading", "kind": "range", "unit": "%"},
    {"key": "pctheldinst", "label": "% Held by Institutions", "category": "Price & Trading", "kind": "range", "unit": "%"},

    # ---- short interest ----
    {"key": "short_percentage_of_shares_outstanding.value", "label": "Short % of Shares Out.", "category": "Short Interest", "kind": "range", "unit": "%"},
    {"key": "short_percentage_of_float.value", "label": "Short % of Float", "category": "Short Interest", "kind": "range", "unit": "%"},
    {"key": "short_interest.value", "label": "Short Interest (shares)", "category": "Short Interest", "kind": "range"},
    {"key": "short_interest_percentage_change.value", "label": "Short Interest % Change", "category": "Short Interest", "kind": "range", "unit": "%"},
    {"key": "days_to_cover_short.value", "label": "Days to Cover Short", "category": "Short Interest", "kind": "range"},

    # ---- valuation ----
    {"key": "peratio.lasttwelvemonths", "label": "P/E (TTM)", "category": "Valuation", "kind": "range"},
    {"key": "pegratio_5y", "label": "PEG Ratio (5Y)", "category": "Valuation", "kind": "range"},
    {"key": "pricebookratio.quarterly", "label": "Price/Book (Qtrly)", "category": "Valuation", "kind": "range"},
    {"key": "bookvalueshare.lasttwelvemonths", "label": "Book Value / Share", "category": "Valuation", "kind": "range", "unit": "$"},
    {"key": "lastclosemarketcaptotalrevenue.lasttwelvemonths", "label": "Market Cap / Revenue", "category": "Valuation", "kind": "range"},
    {"key": "lastclosetevtotalrevenue.lasttwelvemonths", "label": "EV / Revenue", "category": "Valuation", "kind": "range"},
    {"key": "lastclosepricetangiblebookvalue.lasttwelvemonths", "label": "Price / Tangible Book", "category": "Valuation", "kind": "range"},

    # ---- profitability ----
    {"key": "dividendyield", "label": "Dividend Yield", "category": "Profitability", "kind": "range", "unit": "%"},
    {"key": "forward_dividend_yield", "label": "Forward Dividend Yield", "category": "Profitability", "kind": "range", "unit": "%"},
    {"key": "dividendpershare.lasttwelvemonths", "label": "Dividend / Share (TTM)", "category": "Profitability", "kind": "range", "unit": "$"},
    {"key": "forward_dividend_per_share", "label": "Forward Dividend / Share", "category": "Profitability", "kind": "range", "unit": "$"},
    {"key": "consecutive_years_of_dividend_growth_count", "label": "Consecutive Years of Dividend Growth", "category": "Profitability", "kind": "range"},
    {"key": "returnonequity.lasttwelvemonths", "label": "Return on Equity (TTM)", "category": "Profitability", "kind": "range", "unit": "%"},
    {"key": "returnonassets.lasttwelvemonths", "label": "Return on Assets (TTM)", "category": "Profitability", "kind": "range", "unit": "%"},
    {"key": "returnontotalcapital.lasttwelvemonths", "label": "Return on Total Capital (TTM)", "category": "Profitability", "kind": "range", "unit": "%"},

    # ---- leverage ----
    {"key": "totaldebtequity.lasttwelvemonths", "label": "Total Debt / Equity", "category": "Leverage", "kind": "range"},
    {"key": "ltdebtequity.lasttwelvemonths", "label": "LT Debt / Equity", "category": "Leverage", "kind": "range"},
    {"key": "netdebtebitda.lasttwelvemonths", "label": "Net Debt / EBITDA", "category": "Leverage", "kind": "range"},
    {"key": "totaldebtebitda.lasttwelvemonths", "label": "Total Debt / EBITDA", "category": "Leverage", "kind": "range"},
    {"key": "lastclosetevebitda.lasttwelvemonths", "label": "EV / EBITDA", "category": "Leverage", "kind": "range"},
    {"key": "lastclosetevebit.lasttwelvemonths", "label": "EV / EBIT", "category": "Leverage", "kind": "range"},
    {"key": "ebitdainterestexpense.lasttwelvemonths", "label": "EBITDA / Interest Expense", "category": "Leverage", "kind": "range"},
    {"key": "ebitinterestexpense.lasttwelvemonths", "label": "EBIT / Interest Expense", "category": "Leverage", "kind": "range"},

    # ---- liquidity ----
    {"key": "currentratio.lasttwelvemonths", "label": "Current Ratio", "category": "Liquidity", "kind": "range"},
    {"key": "quickratio.lasttwelvemonths", "label": "Quick Ratio", "category": "Liquidity", "kind": "range"},
    {"key": "operatingcashflowtocurrentliabilities.lasttwelvemonths", "label": "Operating Cash Flow / Current Liabilities", "category": "Liquidity", "kind": "range"},
    {"key": "altmanzscoreusingtheaveragestockinformationforaperiod.lasttwelvemonths", "label": "Altman Z-Score", "category": "Liquidity", "kind": "range"},

    # ---- income statement ----
    {"key": "totalrevenues.lasttwelvemonths", "label": "Total Revenue (TTM)", "category": "Income Statement", "kind": "range", "unit": "$"},
    {"key": "totalrevenues1yrgrowth.lasttwelvemonths", "label": "Revenue Growth (1Y)", "category": "Income Statement", "kind": "range", "unit": "%"},
    {"key": "quarterlyrevenuegrowth.quarterly", "label": "Revenue Growth (Qtrly YoY)", "category": "Income Statement", "kind": "range", "unit": "%"},
    {"key": "grossprofit.lasttwelvemonths", "label": "Gross Profit (TTM)", "category": "Income Statement", "kind": "range", "unit": "$"},
    {"key": "grossprofitmargin.lasttwelvemonths", "label": "Gross Margin", "category": "Income Statement", "kind": "range", "unit": "%"},
    {"key": "ebitda.lasttwelvemonths", "label": "EBITDA (TTM)", "category": "Income Statement", "kind": "range", "unit": "$"},
    {"key": "ebitdamargin.lasttwelvemonths", "label": "EBITDA Margin", "category": "Income Statement", "kind": "range", "unit": "%"},
    {"key": "ebitda1yrgrowth.lasttwelvemonths", "label": "EBITDA Growth (1Y)", "category": "Income Statement", "kind": "range", "unit": "%"},
    {"key": "ebit.lasttwelvemonths", "label": "EBIT (TTM)", "category": "Income Statement", "kind": "range", "unit": "$"},
    {"key": "operatingincome.lasttwelvemonths", "label": "Operating Income (TTM)", "category": "Income Statement", "kind": "range", "unit": "$"},
    {"key": "netincomeis.lasttwelvemonths", "label": "Net Income (TTM)", "category": "Income Statement", "kind": "range", "unit": "$"},
    {"key": "netincomemargin.lasttwelvemonths", "label": "Net Margin", "category": "Income Statement", "kind": "range", "unit": "%"},
    {"key": "netincome1yrgrowth.lasttwelvemonths", "label": "Net Income Growth (1Y)", "category": "Income Statement", "kind": "range", "unit": "%"},
    {"key": "epsgrowth.lasttwelvemonths", "label": "EPS Growth (TTM)", "category": "Income Statement", "kind": "range", "unit": "%"},
    {"key": "dilutedeps1yrgrowth.lasttwelvemonths", "label": "Diluted EPS Growth (1Y)", "category": "Income Statement", "kind": "range", "unit": "%"},
    {"key": "netepsbasic.lasttwelvemonths", "label": "Basic EPS (TTM)", "category": "Income Statement", "kind": "range", "unit": "$"},
    {"key": "netepsdiluted.lasttwelvemonths", "label": "Diluted EPS (TTM)", "category": "Income Statement", "kind": "range", "unit": "$"},
    {"key": "basicepscontinuingoperations.lasttwelvemonths", "label": "Basic EPS, Continuing Ops (TTM)", "category": "Income Statement", "kind": "range", "unit": "$"},
    {"key": "dilutedepscontinuingoperations.lasttwelvemonths", "label": "Diluted EPS, Continuing Ops (TTM)", "category": "Income Statement", "kind": "range", "unit": "$"},

    # ---- balance sheet ----
    {"key": "totalassets.lasttwelvemonths", "label": "Total Assets (TTM)", "category": "Balance Sheet", "kind": "range", "unit": "$"},
    {"key": "totalcurrentassets.lasttwelvemonths", "label": "Total Current Assets (TTM)", "category": "Balance Sheet", "kind": "range", "unit": "$"},
    {"key": "totalcurrentliabilities.lasttwelvemonths", "label": "Total Current Liabilities (TTM)", "category": "Balance Sheet", "kind": "range", "unit": "$"},
    {"key": "totalcashandshortterminvestments.lasttwelvemonths", "label": "Cash & Short-Term Investments (TTM)", "category": "Balance Sheet", "kind": "range", "unit": "$"},
    {"key": "totaldebt.lasttwelvemonths", "label": "Total Debt (TTM)", "category": "Balance Sheet", "kind": "range", "unit": "$"},
    {"key": "totalequity.lasttwelvemonths", "label": "Total Equity (TTM)", "category": "Balance Sheet", "kind": "range", "unit": "$"},
    {"key": "totalcommonequity.lasttwelvemonths", "label": "Total Common Equity (TTM)", "category": "Balance Sheet", "kind": "range", "unit": "$"},
    {"key": "totalsharesoutstanding", "label": "Total Shares Outstanding", "category": "Balance Sheet", "kind": "range"},
    {"key": "totalcommonsharesoutstanding.lasttwelvemonths", "label": "Total Common Shares Outstanding (TTM)", "category": "Balance Sheet", "kind": "range"},

    # ---- cash flow ----
    {"key": "cashfromoperations.lasttwelvemonths", "label": "Cash From Operations (TTM)", "category": "Cash Flow", "kind": "range", "unit": "$"},
    {"key": "cashfromoperations1yrgrowth.lasttwelvemonths", "label": "Cash From Operations Growth (1Y)", "category": "Cash Flow", "kind": "range", "unit": "%"},
    {"key": "leveredfreecashflow.lasttwelvemonths", "label": "Levered Free Cash Flow (TTM)", "category": "Cash Flow", "kind": "range", "unit": "$"},
    {"key": "leveredfreecashflow1yrgrowth.lasttwelvemonths", "label": "Levered FCF Growth (1Y)", "category": "Cash Flow", "kind": "range", "unit": "%"},
    {"key": "unleveredfreecashflow.lasttwelvemonths", "label": "Unlevered Free Cash Flow (TTM)", "category": "Cash Flow", "kind": "range", "unit": "$"},
    {"key": "capitalexpenditure.lasttwelvemonths", "label": "Capital Expenditure (TTM)", "category": "Cash Flow", "kind": "range", "unit": "$"},

    # ---- esg ----
    {"key": "esg_score", "label": "ESG Score", "category": "ESG", "kind": "range"},
    {"key": "environmental_score", "label": "Environmental Score", "category": "ESG", "kind": "range"},
    {"key": "social_score", "label": "Social Score", "category": "ESG", "kind": "range"},
    {"key": "governance_score", "label": "Governance Score", "category": "ESG", "kind": "range"},
    {"key": "highest_controversy", "label": "Highest Controversy", "category": "ESG", "kind": "range"},
]
_FIELD_BY_KEY = {f["key"]: f for f in FIELD_CATALOG}

# A few one-click starting points, mirroring yfinance's own predefined queries
# (see yf.PREDEFINED_SCREENER_QUERIES) but expressed as filters this UI understands.
PRESETS = [
    {
        "key": "day_gainers", "label": "Day Gainers",
        "filters": [
            {"field": "percentchange", "op": "gt", "value": 3},
            {"field": "intradaymarketcap", "op": "gte", "value": 2_000_000_000},
            {"field": "intradayprice", "op": "gte", "value": 5},
            {"field": "dayvolume", "op": "gt", "value": 15000},
        ],
        "sort_field": "percentchange", "sort_asc": False,
    },
    {
        "key": "day_losers", "label": "Day Losers",
        "filters": [
            {"field": "percentchange", "op": "lt", "value": -2.5},
            {"field": "intradaymarketcap", "op": "gte", "value": 2_000_000_000},
            {"field": "intradayprice", "op": "gte", "value": 5},
            {"field": "dayvolume", "op": "gt", "value": 20000},
        ],
        "sort_field": "percentchange", "sort_asc": True,
    },
    {
        "key": "undervalued_large_caps", "label": "Undervalued Large Caps",
        "filters": [
            {"field": "peratio.lasttwelvemonths", "op": "btwn", "min": 0, "max": 20},
            {"field": "pegratio_5y", "op": "lt", "value": 1},
            {"field": "intradaymarketcap", "op": "btwn", "min": 10_000_000_000, "max": 100_000_000_000},
        ],
        "sort_field": "intradaymarketcap", "sort_asc": False,
    },
    {
        "key": "growth_technology_stocks", "label": "Growth Tech",
        "filters": [
            {"field": "quarterlyrevenuegrowth.quarterly", "op": "gte", "value": 25},
            {"field": "epsgrowth.lasttwelvemonths", "op": "gte", "value": 25},
            {"field": "sector", "op": "is-in", "values": ["Technology"]},
        ],
        "sort_field": "intradaymarketcap", "sort_asc": False,
    },
    {
        "key": "most_shorted", "label": "Most Shorted",
        "filters": [
            {"field": "intradayprice", "op": "gt", "value": 1},
            {"field": "avgdailyvol3m", "op": "gt", "value": 200000},
        ],
        "sort_field": "short_percentage_of_shares_outstanding.value", "sort_asc": False,
    },
]

_RANGE_OPS = {"gt", "gte", "lt", "lte", "btwn"}
_CHOICE_OPS = {"eq", "is-in"}


def screener_fields() -> dict:
    """The full filterable field catalog + presets, for the screener UI."""
    return {"fields": FIELD_CATALOG, "presets": PRESETS}


def _num(v):
    try:
        f = float(v)
        return None if (f != f or f in (float("inf"), float("-inf"))) else f
    except (TypeError, ValueError):
        return None


def _build_clause(f: dict) -> EquityQuery:
    key = f.get("field")
    op = f.get("op")
    spec = _FIELD_BY_KEY.get(key)
    if spec is None:
        raise ValueError(f"unknown screener field {key!r}")

    if spec["kind"] == "multi":
        if op not in _CHOICE_OPS:
            raise ValueError(f"{key} only supports eq/is-in, got {op!r}")
        values = f.get("values")
        if values is None and f.get("value") is not None:
            values = [f["value"]]
        values = [str(v) for v in (values or []) if str(v).strip()]
        if not values:
            raise ValueError(f"{key} needs at least one value")
        if len(values) == 1:
            return EquityQuery("eq", [key, values[0]])
        return EquityQuery("is-in", [key, *values])

    if spec["kind"] == "range":
        if op not in _RANGE_OPS:
            raise ValueError(f"{key} only supports gt/gte/lt/lte/btwn, got {op!r}")
        if op == "btwn":
            lo, hi = _num(f.get("min")), _num(f.get("max"))
            if lo is None or hi is None:
                raise ValueError(f"{key} btwn needs min and max")
            return EquityQuery("btwn", [key, lo, hi])
        val = _num(f.get("value"))
        if val is None:
            raise ValueError(f"{key} needs a numeric value")
        return EquityQuery(op, [key, val])

    raise ValueError(f"unsupported field kind for {key}")


def _build_query(filters: list[dict]) -> EquityQuery | None:
    clauses = [_build_clause(f) for f in (filters or [])]
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else EquityQuery("and", clauses)


def _pick(q: dict, *names):
    for n in names:
        v = q.get(n)
        if v is not None:
            return v
    return None


def _map_quote(q: dict) -> dict:
    return {
        "ticker": q.get("symbol"),
        "name": _pick(q, "shortName", "longName", "displayName") or q.get("symbol"),
        "exchange": _pick(q, "fullExchangeName", "exchange"),
        "price": _num(_pick(q, "regularMarketPrice", "postMarketPrice")),
        "dayChangePct": _num(q.get("regularMarketChangePercent")),
        "marketCap": _num(q.get("marketCap")),
        "peTrailing": _num(q.get("trailingPE")),
        "peForward": _num(q.get("forwardPE")),
        "priceToBook": _num(q.get("priceToBook")),
        "dividendYield": _num(q.get("dividendYield")),
        "analystRating": q.get("averageAnalystRating"),
        "volume": _num(q.get("regularMarketVolume")),
        "avgVolume3M": _num(q.get("averageDailyVolume3Month")),
        "yearLow": _num(q.get("fiftyTwoWeekLow")),
        "yearHigh": _num(q.get("fiftyTwoWeekHigh")),
        "beta": _num(q.get("beta")),
    }


def run_screen(filters: list[dict], *, sort_field: str = "intradaymarketcap",
                sort_asc: bool = False, offset: int = 0, size: int = 50) -> dict:
    """Run a custom screen against Yahoo's full equity universe (region=us).
    Raises ValueError for a malformed filter (caller maps this to HTTP 400)."""
    size = max(1, min(int(size or 50), 250))
    offset = max(0, int(offset or 0))

    clauses = [EquityQuery("eq", ["region", "us"])]
    custom = _build_query(filters)
    if custom is not None:
        clauses.append(custom)
    query = clauses[0] if len(clauses) == 1 else EquityQuery("and", clauses)

    cache_key = hashlib.sha1(json.dumps(
        {"q": query.to_dict(), "sf": sort_field, "sa": sort_asc, "o": offset, "s": size},
        sort_keys=True,
    ).encode()).hexdigest()

    now = time.time()
    hit = _RESULTS_CACHE.get(cache_key)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    cached = cache.get("screener", cache_key)
    if cached is not cache.MISS:
        value, age = cached
        _RESULTS_CACHE[cache_key] = (now - age, value)
        return value

    def _do():
        sess = yf_session()
        kwargs = dict(offset=offset, size=size, sortField=sort_field, sortAsc=sort_asc)
        if sess is not None:
            try:
                return yf.screen(query, session=sess, **kwargs)
            except Exception:  # noqa: BLE001 — fall back to yfinance's own session
                pass
        return yf.screen(query, **kwargs)

    resp = yf_retry(_do, retry_empty=False) or {}
    out = {
        "total": int(resp.get("total") or 0),
        "rows": [_map_quote(q) for q in (resp.get("quotes") or [])],
    }
    _RESULTS_CACHE[cache_key] = (now, out)
    cache.set("screener", cache_key, out, _TTL)
    return out
