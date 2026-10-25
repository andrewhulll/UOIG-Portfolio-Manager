# Financials tab: full statements + consensus (yfinance)

Status: plan only, nothing built. Source of truth for data availability is the yfinance 1.7.0 probe (AAPL, JPM, ASML, 7203.T).

## 1. What the tab does today

- `src/ingest/research.py::_financials` reads `quarterly_income_stmt` + `quarterly_cashflow` and returns `{bars, rows, statement, caption}`: a 5-quarter revenue/net income bar chart, a YoY row table, and a 4-quarter income statement grid.
- It ships inside the `/api/stock/{ticker}` bundle (`_closed_payload`). Owned holdings read a nightly snapshot (`closed_snapshot`, written by `src/ingest/snapshots.py`) and never hit Yahoo live; unowned names fetch live with a 15-minute cache.
- Frontend: `_renderFinancials` / `_statementGrid` in `web/src/App.jsx` (~L1370+), styled inline with the terminal's dark card system (`#0e1422` cards, `#1d2840` borders, IBM Plex Sans/Mono).
- Consensus, estimates and the 5 latest broker actions already live on the **Research** tab (`_research`, `_consensus`).

## 2. Scope

**In:** income statement, balance sheet, cash flow (annual / quarterly / TTM), derived ratios, valuation snapshot, and a full consensus section (estimates, revisions, surprises, price targets, rating trend, complete broker log).
**Out (yfinance can't supply):** individual sell-side models, segment/geographic revenue, guidance, KPIs. The tab will say so in one line rather than leave a gap.

## 3. Data map

| Section | yfinance source | Notes |
|---|---|---|
| Income stmt | `income_stmt`, `quarterly_income_stmt` | 33–45 rows, 4–5 yrs / 5–7 qtrs |
| Balance sheet | `balance_sheet`, `quarterly_balance_sheet` | 50–90 rows |
| Cash flow | `cashflow`, `quarterly_cashflow` | 45–57 rows |
| TTM | **compute ourselves** from last 4 quarters | `ttm_*` dates were stale for JPM/ASML cash flow (showed 2025-06-30). Sum flows, take latest for balance sheet |
| EPS/revenue estimates | `earnings_estimate`, `revenue_estimate` | avg/low/high/analysts/growth for `0q,+1q,0y,+1y` |
| Revisions | `eps_trend` | current vs 7/30/60/90 days ago |
| Surprises | `earnings_history` | last 4 qtrs actual vs est |
| Growth | `growth_estimates` | stock vs index, incl. LTG |
| Targets | `analyst_price_targets` | low/mean/median/high/current |
| Rating trend | `recommendations_summary` | 4 monthly buckets (existing code reads only row 0) |
| Broker log | `upgrades_downgrades` | up to ~1,000 rows; empty for some non-US names |
| Valuation | `info` / `fast_info` | P/E, fwd P/E, P/S, P/B, EV/EBITDA, PEG, mkt cap. Verify which fields are populated before committing to each |
| Filings | `sec_filings` | links to 10-K/10-Q, US names only |

Derived in our code (no extra calls): gross/operating/EBITDA/net/FCF margins, ROE, ROA, ROIC, current ratio, debt/equity, net debt/EBITDA, interest coverage, FCF conversion, capex % revenue, buyback + dividend yield on FCF, diluted share count change, YoY and QoQ growth per row, common-size percentages.

## 4. Backend design

**New module `src/ingest/statements.py`** (keeps `research.py` from growing further) exposing `build_statements(ticker) -> dict`. Payload shape:

```
{ ticker, currency: {reporting, trading}, fiscalYearEnd: "Sep",
  statements: { income|balance|cashflow: {
      annual:    { periods: ["FY2025",...], rows: [{key,label,level,kind,vals:[...]}] },
      quarterly: { periods: ["Q3 FY26",...], rows: [...] },
      ttm:       { period: "TTM Jun-26", vals by key } } },   # income + cashflow only
  ratios:   { annual: [...], quarterly: [...], ttm: {...} },
  valuation:{ ... },
  consensus:{ estimates: [...], revisions: [...], surprises: [...], growth: [...],
              targets: {...}, ratingTrend: [...], brokerLog: [...] },
  fetchedAt, partial: ["balance.quarterly", ...] }
```

Decisions:
1. **Separate endpoint `GET /api/stock/{ticker}/statements`, lazy-loaded when the Financials tab opens.** Three statements x two frequencies x ~50 rows would bloat `/api/stock` for every tab. Keep the existing summary in the bundle so the tab paints instantly, then fill in the rest.
2. **Mirror the existing split.** Owned holdings: read-only from a `stock_fundamentals` cache namespace, filled by the nightly job (add a call in `snapshots.py`; pending state shows the same "nightly snapshot pending" stub). Unowned: live fetch, cached 6h (fundamentals change quarterly; estimates drift slowly), stale-on-failure fallback like `stock_research`.
3. **Per-section try/except**, and a `partial` list so the UI shows "Balance sheet unavailable, retry" instead of failing the whole tab. Never cache an all-empty result (the bug fixed in `3fc426c`).
4. **Curated line-item hierarchy.** A config of ordered keys per statement with level (0 = total, 1 = group, 2 = line) and kind (flow/stock/ratio/eps). Anything yfinance returns that isn't mapped goes in a collapsed "Other line items" group so no data is dropped. A bank variant (JPM has no Gross Profit/Operating Income; uses Net Interest Income, Non-Interest Expense) is chosen when `Gross Profit` and `Operating Income` are both absent, or by sector.
5. **Null-safe numbers.** NaN to null, raw values (not pre-formatted strings) so the client can toggle units ($M / $B / raw) and common-size without a round trip. This departs from `research.py`'s string-formatting convention on purpose; the statements need arithmetic on the client.
6. **Fiscal labelling.** Derive FY end from the annual columns; label estimate periods (`0y`, `+1y`, `0q`, `+1q`) with real fiscal periods ("FY26E", "Q4 FY26E") instead of "Current Yr".
7. **Currency.** ADRs report in a different currency than they trade in (ASML: USD price, EUR statements). Return both and label every statement with the reporting currency; never mix with price-based valuation without noting it.

## 5. Frontend design

The tab lives inside an existing, dense, dark terminal UI, so it should read as native to it. The new work earns its distinctiveness through the table itself, not new chrome.

**Palette (existing tokens, no new hues):** ground `#0b1020`/card `#0e1422`, rule `#1d2840`, text `#cdd6e8`/`#9aa7c2`/`#6b7794`, positive `#21d07a`, negative `#e8674c`, accent blue `#5a93f9`.
**Type:** IBM Plex Sans for labels, IBM Plex Mono with tabular figures for every number, right-aligned. Negatives in parentheses, not colored by default.
**Memorable element:** the statement table. Each row carries a tiny inline sparkline of its own history, and a mode switch changes the same grid between *values*, *YoY %* and *% of revenue/assets* so an analyst reads trend and structure without leaving the table.

Layout (sentence-case labels, no eyebrow text, left-aligned labels, right-aligned numbers):

```
Financials   [Income | Balance | Cash flow]      [Annual | Quarterly]  [Values | YoY | % of rev]  [$B v]  [Export CSV]
------------------------------------------------------------------------------------------------------------
 Snapshot:  Revenue TTM  | Op margin | FCF margin | Net debt/EBITDA | P/E | EV/EBITDA   (compact stat strip)
------------------------------------------------------------------------------------------------------------
 line item                  spark   FY2022   FY2023   FY2024   FY2025   TTM
 Total revenue              ~~~~     394.3    383.3    391.0    416.2    435.1      <- total rows bold, hairline above
   Cost of revenue          ~~~~     ...                                          <- level-2 rows indented, muted
 Gross profit               ...
 > Other line items (12)                                                            <- collapsed
------------------------------------------------------------------------------------------------------------
 Ratios (margins, returns, leverage, cash conversion) as a second grid, same columns
------------------------------------------------------------------------------------------------------------
 Consensus
   Estimates table: EPS + revenue, low-high range bar around the mean, analyst count, growth
   EPS revisions: current vs 7/30/60/90 days   |  Surprises: last 4 qtrs actual vs est
   Price target range with current-price marker  |  Rating trend: 4 monthly stacked bars
   Broker log: full table, filter by firm / action, 100 most recent, target old -> new
```

Behavior notes:
- Sticky first column and sticky header; horizontal scroll inside the card on mobile, with period columns capped to 4 visible by default and "Show all periods".
- Keep the existing revenue/net income chart and 4-quarter grid as the first view under the new controls, so nothing is lost.
- Stale or partial data shows what failed and how to retry, never a silent blank. Empty broker log for non-US names: "Yahoo has no broker actions for this security."
- Keyboard focus visible on all toggles; sparkline animation none (static); respects reduced motion.

## 6. Implementation phases

1. **Backend data layer (done).** `statements.py` (not `fundamentals.py`, which already fills the DB table) with statement normalization, TTM, hierarchy config (standard + bank), ratios. Unit tests with fixture DataFrames (standard, bank, missing statement, all-NaN row).
2. **Caching + endpoint + nightly job.** Cache namespace, `/api/stock/{ticker}/statements`, owned/unowned paths, `snapshots.py` hook. Tests for the stale-on-failure and never-cache-empty paths.
3. **Frontend statements.** Tab switch, annual/quarterly, values/YoY/common-size, units, collapsed other-lines, sparklines, CSV export. Loading, error and pending states reusing `_stkStub`.
4. **Ratios + valuation strip.**
5. **Consensus section.** Reuse `_consensus`; add estimates range bars, revisions, surprises, target range, rating trend, full broker log. Decide whether the Research tab keeps its short copy or links here.
6. **Verification.** Run against AAPL, JPM (bank), ASML (ADR, EUR), 7203.T (JPY, March FY), a small cap, and a ticker with no coverage; check mobile width, dark theme, and that owned-holding pages make zero live Yahoo calls.

## 7. Risks

- Yahoo returns intermittent 404s and rate limits; need retries/backoff in one place, not per call.
- Line-item names differ by company and change over time; the "Other" bucket and bank variant are the safety net.
- Only 4-5 annual and 5-7 quarterly periods; the UI shouldn't imply longer history.
- Payload size per ticker: measure on a large name before adding to the nightly job for all holdings.
- Estimate data for thinly covered names is sparse or absent; every consensus panel needs an empty state.

## 8. Open questions

- Should the Research tab's consensus card stay as-is or become a link into this tab?
- Do we want the nightly job to snapshot fundamentals for coverage (non-owned) names too, or only holdings?
- CSV export: per statement, or one workbook with all three?
