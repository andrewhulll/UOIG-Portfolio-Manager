import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { getStatements } from '../api.js'
import { UNITS, BASE_KEY, BASE_LABEL, autoUnit, fmtValue, fmtPercent, fmtRatio, yoy, pctOfBase, sparkPoints, toCsv, SHARE_KEYS } from './format.js'
import './financials.css'

const STATEMENTS = [['income', 'Income statement'], ['balance', 'Balance sheet'], ['cashflow', 'Cash flow'], ['ratios', 'Ratios']]
const FREQS = [['annual', 'Annual'], ['quarterly', 'Quarterly']]
const STALE_AFTER = 10 * 60 * 1000

// Tab switches unmount the panel; keep fetched payloads here so coming back is instant.
const memo = new Map()

export function useStatements(ticker) {
  const [state, setState] = useState(() => memo.get(ticker) || { status: 'loading' })
  const load = useCallback((force) => {
    const hit = memo.get(ticker)
    if (!force && hit && hit.status === 'ok' && Date.now() - hit.at < STALE_AFTER) { setState(hit); return () => {} }
    let live = true
    setState({ status: 'loading' })
    getStatements(ticker)
      .then((data) => {
        const next = data.snapshotPending ? { status: 'pending' } : { status: 'ok', data, at: Date.now() }
        if (next.status === 'ok') memo.set(ticker, next)
        if (live) setState(next)
      })
      .catch(() => { if (live) setState({ status: 'error' }) })
    return () => { live = false }
  }, [ticker])
  useEffect(() => load(false), [load])
  return [state, () => load(true)]
}

function Segmented({ label, options, value, onChange }) {
  return (
    <div className="fin-seg" role="group" aria-label={label}>
      {options.map(([k, text]) => (
        <button key={k} type="button" aria-pressed={value === k} onClick={() => onChange(k)}>{text}</button>
      ))}
    </div>
  )
}

function Spark({ vals }) {
  const pts = sparkPoints(vals)
  if (!pts) return <span className="fin-spark" aria-hidden="true" />
  const [lx, ly] = pts[pts.length - 1]
  return (
    <svg className="fin-spark" viewBox="0 0 64 18" aria-hidden="true">
      <polyline points={pts.map((p) => p.join(',')).join(' ')} fill="none" stroke="#5a93f9" strokeWidth="1.3" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r="1.8" fill="#7fb0ff" />
    </svg>
  )
}

function Notice({ title, body, action }) {
  return (
    <div className="fin-notice">
      <div className="fin-notice-title">{title}</div>
      <div className="fin-notice-body">{body}</div>
      {action}
    </div>
  )
}

export function StatementsPanel({ ticker, fallback }) {
  const [state, reload] = useStatements(ticker)
  const [stmt, setStmt] = useState('income')
  const [freq, setFreq] = useState('annual')
  const [mode, setMode] = useState('values')
  const [unitPick, setUnitPick] = useState('auto')
  const [showOther, setShowOther] = useState(false)

  const isRatios = stmt === 'ratios'
  const ok = state.status === 'ok'
  const block = ok && !isRatios && state.data.statements ? state.data.statements[stmt] : null
  const ratioGrid = ok && isRatios && state.data.ratios ? state.data.ratios[freq] : null
  // Ratio rows are flat; give them the subtotal weight so they read as a list of headline metrics.
  const grid = isRatios ? (ratioGrid && { ...ratioGrid, other: [], rows: ratioGrid.rows.map((r) => ({ ...r, level: 1, kind: 'ratio' })) })
    : block ? block[freq] : null
  const ttm = isRatios ? (ok && state.data.ratios && state.data.ratios.ttm
      ? { period: state.data.ratios.ttm.period, vals: state.data.ratios.ttm.vals } : null)
    : block && stmt !== 'balance' ? block.ttm : null   // a balance sheet has no trailing sum

  const unit = useMemo(() => (unitPick === 'auto' ? autoUnit(grid ? grid.rows : []) : unitPick), [unitPick, grid])
  const baseKey = BASE_KEY[stmt]
  const ratioFmt = isRatios && grid ? Object.fromEntries(grid.rows.map((r) => [r.key, r.fmt])) : {}
  const lag = freq === 'annual' ? 1 : 4

  if (state.status === 'loading') return <section className="fin-panel"><Notice title="Loading financial statements" body="Pulling income, balance sheet and cash flow from Yahoo Finance." /></section>
  if (state.status === 'pending') return <>{fallback}<section className="fin-panel"><Notice title="Statements aren't ready yet" body="This holding's statements are filled in by the nightly refresh. Run the refresh once and they will appear here." /></section></>
  if (state.status === 'error') return (
    <>{fallback}
      <section className="fin-panel"><Notice title="Couldn't load the full statements" body="The backend may be offline or Yahoo rate-limited the request."
        action={<button type="button" className="fin-btn" onClick={reload}>Try again</button>} /></section></>
  )

  const { data } = state
  if (!data.statements && !data.ratios) return <>{fallback}<section className="fin-panel"><Notice title="No statements for this security" body="Yahoo Finance returned no income statement, balance sheet or cash flow for it." /></section></>

  // Columns run oldest -> newest (the API is newest-first), with TTM last.
  const order = grid ? grid.periods.map((_, i) => i).reverse() : []
  const rows = grid ? [...grid.rows, ...(showOther ? grid.other : [])] : []
  const baseRow = grid ? grid.rows.find((r) => r.key === baseKey) : null
  const cur = data.currency && data.currency.reporting
  const unitNote = UNITS[unit].suffix
  const fye = data.fiscalYearEndMonth
    ? new Date(2000, data.fiscalYearEndMonth - 1, 1).toLocaleString('en-US', { month: 'long' }) : null

  const cell = (row, vals, i, ttmVal, isTtm) => {
    const v = isTtm ? ttmVal : vals[i]
    if (isRatios) return { text: fmtRatio(v, ratioFmt[row.key]), cls: v == null ? 'dim' : '' }
    if (mode === 'pct') {
      // Per-share and share-count rows have no meaningful share of revenue or assets.
      if (row.kind === 'eps' || SHARE_KEYS.has(row.key)) return { text: '—', cls: 'dim' }
      const base = isTtm ? ttm.vals[baseKey] : (baseRow ? baseRow.vals[i] : null)
      const p = pctOfBase(v, base)
      return { text: fmtPercent(p), cls: p == null ? 'dim' : '' }
    }
    if (mode === 'yoy') {
      if (isTtm) return { text: '—', cls: 'dim' }
      const y = yoy(vals, i, lag)
      if (y === 'n/m') return { text: 'n/m', cls: 'dim' }
      return { text: fmtPercent(y), cls: y == null ? 'dim' : y < 0 ? 'neg' : 'pos' }
    }
    return { text: fmtValue(v, row, unit), cls: v == null ? 'dim' : '' }
  }

  const download = () => {
    const csv = toCsv(grid.periods, rows, ttm)
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url; a.download = `${ticker}_${stmt}_${freq}.csv`
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
  }

  const missing = !grid
  return (
    <>
    <section className="fin-panel fin-statements" aria-label="Financial statements">
      <div className="fin-head">
        <h2 className="fin-title">Financial statements<span className="fin-src"> · income_stmt, balance_sheet, cashflow</span></h2>
        <button type="button" className="fin-btn" onClick={download} disabled={missing}>Export CSV</button>
      </div>
      <div className="fin-controls">
        <Segmented label="Statement" options={STATEMENTS} value={stmt} onChange={(k) => { setStmt(k); setShowOther(false) }} />
        <div className="fin-controls-right">
          <Segmented label="Period" options={FREQS} value={freq} onChange={setFreq} />
          {isRatios ? null : <Segmented label="View" options={[['values', 'Values'], ['yoy', 'YoY change'], ['pct', BASE_LABEL[stmt]]]} value={mode} onChange={setMode} />}
          {isRatios ? null : <label className="fin-unit">
            <span className="fin-sr">Units</span>
            <select value={unitPick} onChange={(e) => setUnitPick(e.target.value)} disabled={mode !== 'values'} title={mode !== 'values' ? 'Units apply to the Values view' : undefined}>
              {Object.entries(UNITS).map(([k, u]) => <option key={k} value={k}>{k === 'auto' ? `Units: auto (${UNITS[autoUnit(grid ? grid.rows : [])].label.toLowerCase()})` : u.label}</option>)}
            </select>
          </label>}
        </div>
      </div>

      {missing ? (
        <Notice title={`No ${freq} ${STATEMENTS.find((x) => x[0] === stmt)[1].toLowerCase()} data`}
          body="Yahoo returned nothing for this view. Try the other period." />
      ) : (
        <>
          <div className="fin-meta">
            {isRatios ? <span>Returns use period-end balances. Annual and TTM only; single quarters aren't annualized.</span> : null}
            {cur && !isRatios ? <span>{cur}{mode === 'values' ? `, ${unitNote} (shares in millions, per-share in ${cur})` : ''}</span> : null}
            {fye ? <span>Fiscal year ends {fye}</span> : null}
            {data.isBank ? <span>Bank: cash-flow ratios are not shown</span> : null}
            {data.currency && data.currency.trading && cur && data.currency.trading !== cur ? <span>Prices are in {data.currency.trading}, statements in {cur}</span> : null}
            {state.data.stale ? <span className="fin-warn">Showing the last saved copy; Yahoo didn't respond</span> : null}
          </div>
          <div className="fin-scroll" tabIndex={0} role="region" aria-label={`${STATEMENTS.find((x) => x[0] === stmt)[1]}, ${freq}`}>
            <table className="fin-table">
              <thead>
                <tr>
                  <th scope="col" className="fin-label-col">Line item</th>
                  <th scope="col" className="fin-spark-col"><span className="fin-sr">Trend</span></th>
                  {order.map((i) => <th scope="col" key={i}>{grid.periods[i]}</th>)}
                  {ttm ? <th scope="col" className="fin-ttm">{ttm.period}</th> : null}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, ri) => {
                  const isOther = ri >= grid.rows.length
                  return (
                    <tr key={row.key} className={`fin-l${row.level}${isOther ? ' fin-other' : ''}`}>
                      <th scope="row" className="fin-label-col"><span>{row.label}</span></th>
                      <td className="fin-spark-col"><Spark vals={row.vals} /></td>
                      {order.map((i) => { const c = cell(row, row.vals, i, null, false); return <td key={i} className={c.cls}>{c.text}</td> })}
                      {ttm ? (() => { const c = cell(row, row.vals, 0, ttm.vals[row.key], true); return <td className={`fin-ttm ${c.cls}`}>{c.text}</td> })() : null}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="fin-foot">
            {grid.other && grid.other.length ? (
              <button type="button" className="fin-btn fin-btn-quiet" aria-expanded={showOther} onClick={() => setShowOther(!showOther)}>
                {showOther ? 'Hide' : 'Show'} other line items ({grid.other.length})
              </button>
            ) : <span />}
            <span className="fin-note">Yahoo reports {freq === 'annual' ? 'about four to five years' : 'the last five to seven quarters'}. {ttm ? 'TTM is the sum of the latest four quarters.' : ''}</span>
          </div>
        </>
      )}
    </section>
    </>
  )
}
