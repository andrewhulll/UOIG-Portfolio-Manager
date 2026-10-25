// Pure helpers for the statements grid: unit scaling, number formats, YoY /
// common-size math, sparkline geometry and CSV export. No React, so they can be
// tested directly in node.

// Share counts are always shown in millions, whatever unit the money rows use.
export const SHARE_KEYS = new Set(['dilutedShares', 'sharesOutstanding'])

export const UNITS = {
  auto: { label: 'Auto', div: null },
  K: { label: 'Thousands', div: 1e3, suffix: 'thousands' },
  M: { label: 'Millions', div: 1e6, suffix: 'millions' },
  B: { label: 'Billions', div: 1e9, suffix: 'billions' },
}

// Pick a unit from the headline row's magnitude so a $400B company reads in
// billions and a $300M one in millions.
export function autoUnit(rows) {
  const headline = rows.find((r) => r.level === 0 && !SHARE_KEYS.has(r.key) && r.kind !== 'eps') || rows[0]
  const peak = headline ? Math.max(0, ...headline.vals.map((v) => (v == null ? 0 : Math.abs(v)))) : 0
  return peak >= 1e10 ? 'B' : peak >= 1e7 ? 'M' : 'K'
}

const grouped = (n, dp) => Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })

// Negatives in parentheses, the convention on a statement.
const signed = (v, text) => (v < 0 ? '(' + text + ')' : text)

export function fmtValue(v, row, unit) {
  if (v == null || Number.isNaN(v)) return '—'
  if (row.kind === 'eps') return signed(v, grouped(v, 2))
  if (SHARE_KEYS.has(row.key)) return signed(v, grouped(v / 1e6, 1))
  const div = UNITS[unit].div
  const scaled = v / div
  return signed(v, grouped(scaled, div >= 1e9 ? 2 : div >= 1e6 ? 1 : 0))
}

export function fmtPercent(p, dp = 1) {
  if (p == null || !Number.isFinite(p)) return '—'
  return signed(p, grouped(p * 100, dp) + '%')
}

// Change vs. the same period a year earlier. `lag` is 1 for annual columns and 4
// for quarterly ones. A negative base makes the ratio meaningless, so say so.
export function yoy(vals, i, lag) {
  const cur = vals[i]
  const prior = vals[i + lag]
  if (cur == null || prior == null || prior === 0) return null
  if (prior < 0) return 'n/m'
  return (cur - prior) / prior
}

export function pctOfBase(v, base) {
  if (v == null || base == null || base === 0) return null
  return v / base
}

// Statements shown as a share of one line: revenue, or total assets for balance sheets.
export const BASE_KEY = { income: 'revenue', cashflow: 'revenue', balance: 'totalAssets' }
export const BASE_LABEL = { income: '% of revenue', cashflow: '% of revenue', balance: '% of assets' }

// Sparkline points over oldest -> newest (the grid reads newest-first from the API).
export function sparkPoints(vals, w = 64, h = 18, pad = 2) {
  const pts = vals.map((v, i) => [i, v]).filter(([, v]) => v != null).reverse()
  if (pts.length < 3) return null
  const xs = vals.length - 1 || 1
  const nums = pts.map(([, v]) => v)
  const lo = Math.min(...nums)
  const hi = Math.max(...nums)
  const span = hi - lo || 1
  // pts is oldest-first after the reverse, so x runs left -> right in time.
  return pts.map(([i, v]) => [
    +(pad + ((xs - i) / xs) * (w - 2 * pad)).toFixed(1),
    +(h - pad - ((v - lo) / span) * (h - 2 * pad)).toFixed(1),
  ])
}

const csvCell = (x) => {
  const t = x == null ? '' : String(x)
  return /[",\n]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t
}

// Raw (unscaled) values, so an export is never rounded by the on-screen unit.
export function toCsv(periods, rows, ttm) {
  const header = ['Line item', ...periods, ...(ttm ? [ttm.period] : [])]
  const lines = [header, ...rows.map((r) => [r.label, ...r.vals, ...(ttm ? [ttm.vals[r.key]] : [])])]
  return lines.map((l) => l.map(csvCell).join(',')).join('\n')
}

// ---------- ratios, valuation, consensus ----------
export function fmtRatio(v, fmt) {
  if (v == null || !Number.isFinite(v)) return '—'
  return fmt === 'pct' ? fmtPercent(v) : signed(v, grouped(v, 2) + 'x')
}

// Compact money for market caps and revenue estimates: 5.07T, 416.2B, 32.5M.
export function fmtCompact(v) {
  if (v == null || !Number.isFinite(v)) return '—'
  const a = Math.abs(v)
  const [d, s, dp] = a >= 1e12 ? [1e12, 'T', 2] : a >= 1e9 ? [1e9, 'B', 1] : a >= 1e6 ? [1e6, 'M', 1] : [1, '', 0]
  return signed(v, grouped(v / d, dp) + s)
}

export const fmtPrice = (v) => (v == null || !Number.isFinite(v) ? '—' : grouped(v, 2))

// Yahoo's dividendYield arrives already in percent (0.31 means 0.31%).
export const VALUATION_ITEMS = [
  ['marketCap', 'Market cap', (v) => fmtCompact(v)],
  ['trailingPE', 'P/E', (v) => grouped(v, 1) + 'x'],
  ['forwardPE', 'Forward P/E', (v) => grouped(v, 1) + 'x'],
  ['peg', 'PEG', (v) => grouped(v, 2)],
  ['priceToSales', 'Price / sales', (v) => grouped(v, 1) + 'x'],
  ['priceToBook', 'Price / book', (v) => grouped(v, 1) + 'x'],
  ['evToEbitda', 'EV / EBITDA', (v) => grouped(v, 1) + 'x'],
  ['dividendYield', 'Dividend yield', (v) => grouped(v, 2) + '%'],
  ['beta', 'Beta', (v) => grouped(v, 2)],
]

export function valuationCells(valuation) {
  if (!valuation) return []
  return VALUATION_ITEMS.filter(([k]) => valuation[k] != null).map(([k, label, f]) => ({ key: k, label, text: f(valuation[k]) }))
}

// Where a point sits on a [lo, hi] track, as 0-100, clamped. Null when the track is degenerate.
export function trackPos(v, lo, hi) {
  if (v == null || lo == null || hi == null || hi <= lo) return null
  return Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100))
}

// Mean target vs the current price, as a fraction.
export const upside = (mean, current) => (mean == null || !current ? null : mean / current - 1)

// Change in the consensus EPS estimate over the last 90 days, as a fraction.
export function revisionChange(row) {
  if (row.current == null || row.d90 == null || row.d90 === 0) return null
  return (row.current - row.d90) / Math.abs(row.d90)
}

export const ACTION_LABEL = { up: 'Upgrade', down: 'Downgrade', main: 'Maintains', reit: 'Reiterates', init: 'Initiates', target: 'Target change' }

export function gradeText(r) {
  if (r.from && r.to && r.from !== r.to) return `${r.from} → ${r.to}`
  return r.to || r.from || '—'
}

export function targetText(r) {
  if (r.target == null) return '—'
  return r.priorTarget != null && r.priorTarget !== r.target ? `${fmtPrice(r.priorTarget)} → ${fmtPrice(r.target)}` : fmtPrice(r.target)
}

// Rating-trend bars: oldest -> newest, each segment a share of that month's analysts.
export const RATING_KEYS = [['strongBuy', 'Strong buy', '#1ba862'], ['buy', 'Buy', '#21d07a'], ['hold', 'Hold', '#7e8aa6'],
  ['sell', 'Sell', '#f08a5d'], ['strongSell', 'Strong sell', '#e8674c']]
export const ratingLabel = (p) => (p === '0m' ? 'Now' : /^-(\d+)m$/.test(p) ? `${p.slice(1, -1)} mo ago` : p)
export const ratingOrder = (rows) => [...rows].reverse()

export function filterBroker(log, { firm = '', action = 'all' } = {}) {
  const q = firm.trim().toLowerCase()
  return log.filter((r) => (action === 'all' || r.action === action) && (!q || (r.firm || '').toLowerCase().includes(q)))
}
