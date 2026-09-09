import React from 'react'
import { s } from '../ui.js'
import { getScreenerFields, runScreener } from './api.js'

const fieldStyle = s("background:#0a0e18;border:1px solid #1d2840;border-radius:7px;color:#e8edf7;font:400 11.5px 'IBM Plex Sans';padding:8px 10px;outline:none;")
const eyebrow = s("font:600 9px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#5d6a85;")
const num = (n, d = 2) => n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
const kd = (n) => {
  if (n == null) return '—'
  const a = Math.abs(n)
  if (a >= 1e12) return '$' + (n / 1e12).toFixed(2) + 'T'
  if (a >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B'
  if (a >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M'
  return '$' + Math.round(n).toLocaleString('en-US')
}
const vol = (n) => {
  if (n == null) return '—'
  const a = Math.abs(n)
  if (a >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (a >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (a >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(Math.round(n))
}
const pct = (n, d = 2) => n == null ? '—' : (n >= 0 ? '+' : '') + n.toFixed(d) + '%'
const col = (n) => n == null ? '#6b7794' : (n >= 0 ? '#21d07a' : '#ff5666')
const UNIT_HINT = { '%': 'percent', '$': 'dollars' }

const COLS_TEMPLATE = '64px 1fr 90px 76px 72px 92px 76px 72px 64px 76px 92px 110px'

// Result columns wired to a sortable screener field key where one exists.
const RESULT_COLS = [
  { key: 'ticker', label: 'Ticker', align: 'left' },
  { key: 'name', label: 'Name', align: 'left' },
  { key: 'exchange', label: 'Exchange', align: 'left' },
  { key: 'price', label: 'Price', align: 'right', sortField: 'intradayprice', fmt: (r) => num(r.price) },
  { key: 'dayChangePct', label: 'Day', align: 'right', sortField: 'percentchange', fmt: (r) => pct(r.dayChangePct), color: (r) => col(r.dayChangePct) },
  { key: 'marketCap', label: 'Mkt Cap', align: 'right', sortField: 'intradaymarketcap', fmt: (r) => kd(r.marketCap) },
  { key: 'peTrailing', label: 'P/E (TTM)', align: 'right', sortField: 'peratio.lasttwelvemonths', fmt: (r) => num(r.peTrailing, 1) },
  { key: 'peForward', label: 'Fwd P/E', align: 'right', fmt: (r) => num(r.peForward, 1) },
  { key: 'priceToBook', label: 'P/B', align: 'right', sortField: 'pricebookratio.quarterly', fmt: (r) => num(r.priceToBook, 1) },
  { key: 'dividendYield', label: 'Div Yield', align: 'right', sortField: 'dividendyield', fmt: (r) => r.dividendYield == null ? '—' : r.dividendYield.toFixed(2) + '%' },
  { key: 'avgVolume3M', label: 'Avg Vol (3M)', align: 'right', sortField: 'avgdailyvol3m', fmt: (r) => vol(r.avgVolume3M) },
  { key: 'analystRating', label: 'Analyst Rating', align: 'right', fmt: (r) => r.analystRating || '—' },
]

function defaultFilterState(field) {
  return field.kind === 'multi' ? { values: [] } : { min: '', max: '' }
}

function toApiFilter(field, state) {
  if (field.kind === 'multi') {
    if (!state.values || !state.values.length) return null
    return { field: field.key, op: 'is-in', values: state.values }
  }
  const min = state.min === '' ? null : Number(state.min)
  const max = state.max === '' ? null : Number(state.max)
  if (min == null && max == null) return null
  if (min != null && max != null) return { field: field.key, op: 'btwn', min, max }
  if (min != null) return { field: field.key, op: 'gte', value: min }
  return { field: field.key, op: 'lte', value: max }
}

function FilterChip({ field, state, onChange, onRemove }) {
  const [search, setSearch] = React.useState('')
  const label = field.unit ? `${field.label} (${UNIT_HINT[field.unit] || field.unit})` : field.label

  if (field.kind === 'multi') {
    const options = search
      ? field.values.filter((v) => v.toLowerCase().indexOf(search.toLowerCase()) >= 0)
      : field.values
    const toggle = (v) => {
      const set = new Set(state.values)
      set.has(v) ? set.delete(v) : set.add(v)
      onChange({ ...state, values: Array.from(set) })
    }
    return (
      <div style={s('background:#0a0e18;border:1px solid #1d2840;border-radius:8px;padding:10px 12px;')}>
        <div style={s('display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;')}>
          <span style={s("font:600 11px 'IBM Plex Sans';color:#e8edf7;")}>
            {label}{state.values.length > 0 && <span style={s('color:#5a93f9;')}> · {state.values.length}</span>}
          </span>
          <span onClick={onRemove} style={s("color:#5d6a85;cursor:pointer;font-size:14px;line-height:1;")}>×</span>
        </div>
        {field.values.length > 8 && (
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search…"
            style={{ ...fieldStyle, width: '100%', padding: '5px 8px', fontSize: 10.5, marginBottom: 6, boxSizing: 'border-box' }} />
        )}
        <div style={s('max-height:146px;overflow-y:auto;display:flex;flex-direction:column;gap:4px;')}>
          {options.map((v) => (
            <label key={v} style={s("display:flex;align-items:center;gap:6px;font:400 10.5px 'IBM Plex Sans';color:#9aa7c2;cursor:pointer;")}>
              <input type="checkbox" checked={state.values.includes(v)} onChange={() => toggle(v)} />
              {v}
            </label>
          ))}
          {options.length === 0 && <span style={s("font-size:10.5px;color:#3c465e;")}>No matches</span>}
        </div>
      </div>
    )
  }
  return (
    <div style={s('background:#0a0e18;border:1px solid #1d2840;border-radius:8px;padding:10px 12px;')}>
      <div style={s('display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;')}>
        <span style={s("font:600 11px 'IBM Plex Sans';color:#e8edf7;")}>{label}</span>
        <span onClick={onRemove} style={s("color:#5d6a85;cursor:pointer;font-size:14px;line-height:1;")}>×</span>
      </div>
      <div style={s('display:flex;align-items:center;gap:6px;')}>
        <input value={state.min} onChange={(e) => onChange({ ...state, min: e.target.value })} placeholder="Min" type="number"
          style={{ ...fieldStyle, width: '100%', minWidth: 0, boxSizing: 'border-box' }} />
        <span style={s('color:#3c465e;flex:0 0 auto;')}>–</span>
        <input value={state.max} onChange={(e) => onChange({ ...state, max: e.target.value })} placeholder="Max" type="number"
          style={{ ...fieldStyle, width: '100%', minWidth: 0, boxSizing: 'border-box' }} />
      </div>
    </div>
  )
}

function AddFilterMenu({ categories, activeKeys, onToggle }) {
  const [open, setOpen] = React.useState(false)
  const [search, setSearch] = React.useState('')
  const ref = React.useRef(null)

  React.useEffect(() => {
    const onDocClick = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const q = search.trim().toLowerCase()
  return (
    <div ref={ref} style={s('position:relative;')}>
      <div onClick={() => setOpen((o) => !o)} className="dc-hover"
        style={s("display:inline-flex;align-items:center;gap:6px;background:#13203a;border:1px solid #28406e;border-radius:7px;padding:7px 13px;cursor:pointer;font:600 11px 'IBM Plex Sans';color:#5a93f9;")}>
        + Add filter
      </div>
      {open && (
        <div style={s('position:absolute;top:calc(100% + 6px);right:0;z-index:20;width:300px;max-height:380px;overflow-y:auto;background:#0e1422;border:1px solid #1d2840;border-radius:10px;box-shadow:0 16px 40px rgba(0,0,0,.55);padding:10px;')}>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search fields…" autoFocus
            style={{ ...fieldStyle, width: '100%', boxSizing: 'border-box', marginBottom: 8 }} />
          {categories.map(([cat, fields]) => {
            const shown = q ? fields.filter((f) => f.label.toLowerCase().indexOf(q) >= 0) : fields
            if (!shown.length) return null
            return (
              <div key={cat} style={s('margin-bottom:8px;')}>
                <div style={{ ...eyebrow, padding: '4px 6px' }}>{cat}</div>
                {shown.map((f) => (
                  <div key={f.key} onClick={() => onToggle(f)} className="dc-row"
                    style={s("display:flex;align-items:center;justify-content:space-between;padding:6px 8px;border-radius:6px;cursor:pointer;font:500 11px 'IBM Plex Sans';")}>
                    <span style={{ color: activeKeys.has(f.key) ? '#5a93f9' : '#cdd6e8' }}>{f.label}</span>
                    {activeKeys.has(f.key) && <span style={s('color:#5a93f9;')}>✓</span>}
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function MarketScreener({ onOpenStock }) {
  const [catalog, setCatalog] = React.useState(null)
  const [catalogError, setCatalogError] = React.useState('')
  const [activeFields, setActiveFields] = React.useState([])       // [field, ...]
  const [filterState, setFilterState] = React.useState({})          // key -> {values} | {min,max}
  const [sortField, setSortField] = React.useState('intradaymarketcap')
  const [sortAsc, setSortAsc] = React.useState(false)
  const [size, setSize] = React.useState(50)
  const [result, setResult] = React.useState(null)
  const [loading, setLoading] = React.useState(false)
  const [runError, setRunError] = React.useState('')

  React.useEffect(() => {
    getScreenerFields().then(setCatalog).catch((e) => setCatalogError(e.message || 'Could not load screener fields'))
  }, [])

  const runScreen = React.useCallback((fields, states, sf, sa, sz) => {
    const filters = fields.map((f) => toApiFilter(f, states[f.key] || defaultFilterState(f))).filter(Boolean)
    setLoading(true); setRunError('')
    runScreener({ filters, sort_field: sf, sort_asc: sa, size: sz })
      .then(setResult)
      .catch((e) => setRunError(e.message || 'Screen failed'))
      .finally(() => setLoading(false))
  }, [])

  // Run once fields are loaded (top names by market cap, no filters) and again
  // whenever Run is clicked.
  React.useEffect(() => {
    if (catalog) runScreen([], {}, sortField, sortAsc, size)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog])

  if (catalogError) {
    return (
      <div style={s('padding:40px;')}>
        <div style={s('background:#111a2e;border:1px solid #1d2840;border-radius:10px;padding:24px;text-align:center;')}>
          <div style={s("font:600 13px 'IBM Plex Sans';color:#e8edf7;margin-bottom:6px;")}>Screener unavailable</div>
          <div style={s("font:500 12px 'IBM Plex Sans';color:#7e8aa6;")}>{catalogError}</div>
        </div>
      </div>
    )
  }
  if (!catalog) {
    return (
      <div style={s("padding:40px;font:500 12px 'IBM Plex Sans';color:#7e8aa6;display:flex;align-items:center;gap:8px;")}>
        <span className="settings-spinner" />Loading screener…
      </div>
    )
  }

  const categories = []
  const seen = new Set()
  catalog.fields.forEach((f) => { if (!seen.has(f.category)) { seen.add(f.category); categories.push(f.category) } })
  const byCategory = categories.map((cat) => [cat, catalog.fields.filter((f) => f.category === cat)])
  const activeKeys = new Set(activeFields.map((f) => f.key))
  const sortableFields = catalog.fields.filter((f) => f.kind === 'range')

  const toggleField = (field) => {
    if (activeKeys.has(field.key)) {
      setActiveFields((a) => a.filter((f) => f.key !== field.key))
      setFilterState((s2) => { const n = { ...s2 }; delete n[field.key]; return n })
    } else {
      setActiveFields((a) => [...a, field])
      setFilterState((s2) => ({ ...s2, [field.key]: defaultFilterState(field) }))
    }
  }

  const applyPreset = (preset) => {
    const fields = preset.filters.map((pf) => catalog.fields.find((f) => f.key === pf.field)).filter(Boolean)
    const states = {}
    preset.filters.forEach((pf) => {
      const field = catalog.fields.find((f) => f.key === pf.field)
      if (!field) return
      if (field.kind === 'multi') { states[pf.field] = { values: pf.values || (pf.value != null ? [pf.value] : []) }; return }
      if (pf.op === 'btwn') { states[pf.field] = { min: String(pf.min), max: String(pf.max) }; return }
      if (pf.op === 'gt' || pf.op === 'gte') { states[pf.field] = { min: String(pf.value), max: '' }; return }
      states[pf.field] = { min: '', max: String(pf.value) }
    })
    setActiveFields(fields)
    setFilterState(states)
    setSortField(preset.sort_field || 'intradaymarketcap')
    setSortAsc(!!preset.sort_asc)
    runScreen(fields, states, preset.sort_field || 'intradaymarketcap', !!preset.sort_asc, size)
  }

  const clearAll = () => {
    setActiveFields([]); setFilterState({})
    runScreen([], {}, sortField, sortAsc, size)
  }

  const onSortCol = (sf) => {
    const asc = sortField === sf ? !sortAsc : false
    setSortField(sf); setSortAsc(asc)
    runScreen(activeFields, filterState, sf, asc, size)
  }

  const loadMore = () => {
    const bigger = Math.min(size + 50, 250)
    setSize(bigger)
    runScreen(activeFields, filterState, sortField, sortAsc, bigger)
  }

  const rows = (result && result.rows) || []
  const total = result ? result.total : 0

  return (
    <div style={s('padding:16px;display:flex;flex-direction:column;gap:16px;')}>
      {/* QUERY BUILDER — one panel: pick a starting point, refine it, run it. */}
      <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:12px;padding:16px 18px;display:flex;flex-direction:column;gap:14px;')}>
        <div style={s('display:flex;flex-direction:column;gap:9px;')}>
          <div style={eyebrow}>Quick screens</div>
          <div style={s('display:flex;flex-wrap:wrap;gap:7px;')}>
            {catalog.presets.map((p) => (
              <span key={p.key} onClick={() => applyPreset(p)} className="dc-hover"
                style={s("font:600 10.5px 'IBM Plex Sans';color:#9aa7c2;background:#131c2f;border-radius:7px;padding:6px 12px;cursor:pointer;")}>
                {p.label}
              </span>
            ))}
          </div>
        </div>

        <div style={s('border-top:1px solid #1a2438;padding-top:14px;display:flex;flex-direction:column;gap:11px;')}>
          <div style={s('display:flex;align-items:center;justify-content:space-between;')}>
            <div style={eyebrow}>Filters{activeFields.length > 0 ? ` · ${activeFields.length} active` : ''}</div>
            <AddFilterMenu categories={byCategory} activeKeys={activeKeys} onToggle={toggleField} />
          </div>
          {activeFields.length > 0 ? (
            <div style={s('display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px;')}>
              {activeFields.map((f) => (
                <FilterChip key={f.key} field={f} state={filterState[f.key] || defaultFilterState(f)}
                  onChange={(st) => setFilterState((s2) => ({ ...s2, [f.key]: st }))}
                  onRemove={() => toggleField(f)} />
              ))}
            </div>
          ) : (
            <div style={s("font:500 11px 'IBM Plex Sans';color:#3c465e;")}>No filters yet — add one above or start from a quick screen.</div>
          )}
        </div>

        <div style={s('border-top:1px solid #1a2438;padding-top:14px;display:flex;align-items:center;flex-wrap:wrap;gap:14px;')}>
          <span onClick={() => runScreen(activeFields, filterState, sortField, sortAsc, size)} className="dc-hover"
            style={s("font:600 12px 'IBM Plex Sans';color:#fff;background:#2f6df6;border-radius:8px;padding:9px 20px;cursor:pointer;")}>
            Run screen
          </span>
          {activeFields.length > 0 && (
            <span onClick={clearAll} style={s("font:600 10.5px 'IBM Plex Sans';color:#5a93f9;cursor:pointer;")}>Clear filters</span>
          )}
          <div style={s('display:flex;align-items:center;gap:8px;margin-left:auto;')}>
            <span style={s("font:500 10.5px 'IBM Plex Sans';color:#5d6a85;")}>Sort</span>
            <select value={sortField} onChange={(e) => onSortCol(e.target.value)} style={{ ...fieldStyle, cursor: 'pointer' }}>
              {sortableFields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </select>
            <span onClick={() => onSortCol(sortField)} style={s("cursor:pointer;color:#5d6a85;font-size:13px;")}>{sortAsc ? '↑' : '↓'}</span>
          </div>
          {runError && <span style={s("font:500 11px 'IBM Plex Sans';color:#ff5666;width:100%;")}>{runError}</span>}
        </div>
      </div>

      {/* RESULTS */}
      <div style={s('display:flex;align-items:center;gap:8px;')}>
        {loading && <span className="settings-spinner" />}
        <span style={s("font-family:'IBM Plex Mono';font-size:10.5px;color:#6b7794;")}>
          {loading ? 'Screening the market…' : (result ? `${rows.length.toLocaleString()} shown of ${total.toLocaleString()} matches` : '')}
        </span>
      </div>

      <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;overflow:hidden;')}>
        <div style={{ ...s("display:grid;gap:8px;padding:10px 14px;border-bottom:1px solid #1d2840;font:600 8.5px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;color:#6b7794;"), gridTemplateColumns: COLS_TEMPLATE }}>
          {RESULT_COLS.map((c) => (
            <span key={c.key} onClick={c.sortField ? () => onSortCol(c.sortField) : undefined}
              style={{ ...s(c.sortField ? 'cursor:pointer;' : ''), textAlign: c.align, color: c.sortField === sortField ? '#cdd6e8' : '#6b7794' }}>
              {c.label}{c.sortField === sortField ? (sortAsc ? ' ↑' : ' ↓') : ''}
            </span>
          ))}
        </div>
        {!loading && rows.length === 0 && (
          <div style={s("padding:32px 14px;text-align:center;font:500 11.5px 'IBM Plex Sans';color:#5d6a85;")}>
            No equities match these filters — widen a range or remove one.
          </div>
        )}
        {rows.map((r, i) => (
          <div key={r.ticker} onClick={() => onOpenStock(r.ticker)} className="dc-row"
            style={{ ...s("display:grid;gap:8px;align-items:center;padding:9px 14px;border-bottom:1px solid #131c2f;font-size:11px;cursor:pointer;"), gridTemplateColumns: COLS_TEMPLATE, background: i % 2 ? 'rgba(255,255,255,.014)' : 'transparent' }}>
            {RESULT_COLS.map((c) => (
              <span key={c.key} style={{
                fontFamily: c.key === 'name' || c.key === 'exchange' ? undefined : "'IBM Plex Mono'",
                fontVariantNumeric: c.key === 'name' || c.key === 'exchange' || c.key === 'ticker' || c.key === 'analystRating' ? undefined : 'tabular-nums',
                fontWeight: c.key === 'ticker' ? 600 : 400,
                textAlign: c.align,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                color: c.color ? c.color(r) : (c.key === 'ticker' ? '#e8edf7' : c.key === 'name' ? '#9aa7c2' : c.key === 'exchange' ? '#6b7794' : '#cdd6e8'),
              }}>
                {c.fmt ? c.fmt(r) : r[c.key]}
              </span>
            ))}
          </div>
        ))}
      </div>

      {result && rows.length < total && rows.length >= size && (
        <span onClick={loadMore} style={s("align-self:center;font:600 10.5px 'IBM Plex Sans';color:#5a93f9;cursor:pointer;padding:6px;")}>
          Load 50 more ({rows.length.toLocaleString()} of {total.toLocaleString()})
        </span>
      )}
    </div>
  )
}
