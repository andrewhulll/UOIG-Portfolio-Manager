import React from 'react'
import { getMyCoverage, getMovers, getWatchlist, addWatchlistTicker, removeWatchlistTicker } from '../api.js'
import { s, SECTOR_COLORS } from '../ui.js'
import { smoothPath } from '../charts/PriceChart.jsx'
import './coverage.css'

const color = v => v == null ? '#7e8aa6' : v >= 0 ? '#21d07a' : '#ff5666'
const signed = (v, dp = 1) => v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(dp)}`
const pct = v => v == null ? '—' : `${signed(v)}%`
const price = v => v == null ? '—' : '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const pe = v => v == null ? '—' : `${v.toFixed(1)}x`
const money = v => {
  if (v == null) return '—'
  const a = Math.abs(v)
  const [scale, suffix] = a >= 1e12 ? [1e12, 'T'] : a >= 1e9 ? [1e9, 'B'] : a >= 1e6 ? [1e6, 'M'] : a >= 1e3 ? [1e3, 'K'] : [1, '']
  return `${v < 0 ? '-' : ''}$${(a / scale).toFixed(a >= 1e9 ? 2 : a >= 1e3 ? 1 : 2)}${suffix}`
}
function shortDate(value) {
  if (!value || value === '—') return '—'
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? value + 'T12:00:00' : value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toUpperCase()
}

// Key check also guards the render before effects run after a fund switch.
function useRegion(fetchData, key) {
  const [version, reload] = React.useReducer(v => v + 1, 0)
  const [state, setState] = React.useState({})
  React.useEffect(() => {
    let live = true
    setState({ key })
    fetchData().then(data => { if (live) setState({ key, data }) })
      .catch(e => { if (live) setState({ key, error: e.detail || e.message || 'Please try again.' }) })
    return () => { live = false }
  }, [key, version])
  return { ...(state.key === key ? state : {}), reload }
}
function Loading({ children }) { return <p role="status" className="coverage-muted"><span className="settings-spinner" /> {children}</p> }
function Failure({ title, error, retry }) { return <div role="alert" className="coverage-failure"><strong>{title}</strong><p>{error}</p><button onClick={retry}>Try again</button></div> }

function Spark({ values = [] }) {
  const id = React.useId().replace(/:/g, '')
  const points = values.filter(Number.isFinite)
  if (points.length < 2) return <div style={s('height:52px;display:flex;align-items:center;')} className="coverage-muted">Not enough price history yet</div>
  const lo = Math.min(...points), hi = Math.max(...points), span = hi - lo || 1
  const lineColor = color(points[points.length - 1] - points[0])
  const line = smoothPath(points.map((v, i) => [i / (points.length - 1) * 300, 49 - (v - lo) / span * 46]))
  return <svg viewBox="0 0 300 52" preserveAspectRatio="none" aria-label="One month closing price trend" role="img" style={s('width:100%;height:52px;display:block;')}>
    <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={lineColor} stopOpacity=".22" /><stop offset="1" stopColor={lineColor} stopOpacity=".04" /></linearGradient></defs>
    <path d={`${line} L300,52 L0,52 Z`} fill={`url(#${id})`} />
    <path d={line} fill="none" stroke={lineColor} strokeWidth="1.6" vectorEffect="non-scaling-stroke" strokeLinecap="round" />
  </svg>
}
function Stat({ label, value, sub, valueColor, subColor, title }) {
  return <div className="coverage-stat" title={title}><div className="coverage-label">{label}</div><div className="coverage-stat-value" style={{ color: valueColor || '#cdd6e8' }}>{value}</div><div className="coverage-stat-sub" style={{ color: subColor || '#7e8aa6' }}>{sub}</div></div>
}
function CoverageCard({ card, onOpenStock, fund }) {
  const c = card.consensus
  const upside = c?.mean != null && card.price > 0 ? (c.mean / card.price - 1) * 100 : null
  const points = card.thesis?.points?.slice(0, 3) || []
  const soon = card.earningsInDays != null && card.earningsInDays >= 0 && card.earningsInDays <= 5
  const selectedHeld = card.heldInFund ?? card.held
  const noPosition = card.held && !selectedHeld ? 'NOT HELD IN THIS FUND' : 'COVERAGE ONLY'
  const sectorColor = SECTOR_COLORS[card.sector] || '#7e8aa6'
  const values = (card.series || []).filter(Number.isFinite)
  return <article className="coverage-card" role="link" tabIndex={0} aria-label={`Open ${card.ticker} research`}
    onClick={() => onOpenStock(card.ticker)} onKeyDown={e => { if (e.target === e.currentTarget && e.key === 'Enter') onOpenStock(card.ticker) }}
    style={s('background:#111a2e;border:1px solid #1d2840;border-radius:10px;padding:18px 20px;cursor:pointer;min-width:0;')}>
    <div style={s('display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-start;gap:12px;')}>
      <div style={s('min-width:0;flex:1 1 190px;')}>
        <div style={s('display:flex;align-items:center;flex-wrap:wrap;gap:7px;')}><span className="coverage-symbol">{card.ticker}</span><span className="coverage-badge">{card.held ? 'POSITION' : 'COVERAGE ONLY'}</span>{card.sector && <span className="coverage-badge" style={{ color: sectorColor, background: sectorColor + '18', borderColor: sectorColor + '40' }}>{card.sector}</span>}</div>
        <div className="coverage-ellipsis" style={s('font-size:12.5px;color:#7e8aa6;margin-top:5px;')} title={card.name}>{card.name}{card.exchange ? ` · ${card.exchange}` : ''}</div>
      </div>
      <div style={s('text-align:right;flex:0 1 auto;')}><div className="coverage-price">{price(card.price)}</div><div className="coverage-change"><span style={{ color: color(card.dayChangePct) }}>{pct(card.dayChangePct)}</span><span style={s('color:#3c465e;margin:0 6px;')}>·</span><span style={{ color: color(card.mtdChangePct) }}>MTD {pct(card.mtdChangePct)}</span></div></div>
    </div>
    <div style={s('margin-top:18px;')}><Spark values={values} /><div className="coverage-caption"><span>1M CLOSE{values.length ? ` · ${price(Math.min(...values))}–${price(Math.max(...values))}` : ''}</span><span>CLOSE {card.closeDate || '—'}</span></div></div>
    <div className="coverage-rule" style={s('display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:14px 18px;')}>
      <Stat label={fund === 'all' ? 'PORTFOLIO WEIGHT' : 'FUND WEIGHT'} value={selectedHeld && card.weight != null ? card.weight.toFixed(1) + '%' : '—'} sub={selectedHeld ? `ACTIVE ${signed(card.activeWeightBp, 0)}${card.activeWeightBp == null ? '' : 'BP'}` : noPosition} title="Weight excludes cash; active weight is relative to the fund benchmark." />
      <Stat label="NEXT EARNINGS" value={(card.nextEarningsEstimated ? '~' : '') + shortDate(card.nextEarnings)} sub={card.earningsInDays == null || card.earningsInDays < 0 ? 'DATE UNAVAILABLE' : card.earningsInDays === 0 ? 'TODAY' : `IN ${card.earningsInDays}D`} subColor={soon ? '#f4a531' : undefined} />
      <Stat label="STREET" value={c ? `${c.label.toUpperCase()}${c.total != null ? ` (${c.total})` : ''}` : '—'} sub={upside == null ? 'TARGET UNAVAILABLE' : `${signed(upside, 0)}% TO ${price(c.mean)}`} subColor={color(upside)} />
      <Stat label="MKT CAP" value={money(card.marketCap == null ? null : card.marketCap * 1e9)} sub={`REV ${pct(card.revGrowth)}`} title="Provider year-over-year revenue growth." />
      <Stat label="FWD P/E" value={pe(card.forwardPE)} sub={`PORT. SECTOR ${pe(card.sectorForwardPE)}`} title="Market-value-weighted positive forward P/Es in the selected portfolio's UOIG sector group." />
      <Stat label="UNREALIZED" value={selectedHeld ? `${card.unrealized > 0 ? '+' : ''}${money(card.unrealized)}` : '—'} valueColor={selectedHeld ? color(card.unrealized) : undefined} sub={selectedHeld ? `BASIS ${price(card.costBasis)}` : card.held ? noPosition : 'NOT HELD'} />
    </div>
    <div className="coverage-rule"><div className="coverage-caption" style={s('margin:0 0 12px;')}><span className="coverage-label">THESIS</span><span>{points.length ? `FILED ${card.thesis.date}${card.thesis.analyst ? ' · ' + card.thesis.analyst : ''}` : 'NO THESIS ON FILE'}</span></div>
      {points.length ? <ol className="coverage-thesis">{points.map((p, i) => <li key={i}><span>{i + 1}</span><div>{p}</div></li>)}</ol> : <p className="coverage-muted">No thesis on file yet.</p>}
    </div>
    <div className="coverage-rule"><div className="coverage-label" style={s('margin-bottom:12px;')}>HEADLINES</div>
      {(card.news || []).length ? card.news.slice(0, 3).map((n, i) => <a className="coverage-headline" key={n.link || i} href={n.link} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}>{n.title}<span>{n.publisher} · {n.ago}</span></a>) : <p className="coverage-muted">No recent headlines available.</p>}
    </div>
  </article>
}
function Movers({ fund, onOpenStock }) {
  const [period, setPeriod] = React.useState('MTD')
  const remote = useRegion(() => getMovers(fund, period), `${fund}:${period}`)
  const data = remote.data
  const list = (rows, positive) => {
    const max = Math.max(...rows.map(r => Math.abs(r.contribution_bp)), 1e-8)
    return <><div className="coverage-label" style={{ color: positive ? '#21d07a' : '#ff5666', margin: '18px 0 10px' }}>TOP {positive ? 'CONTRIBUTORS' : 'DETRACTORS'}</div>
      {!rows.length && <p className="coverage-muted">No {positive ? 'positive' : 'negative'} contributors for this window.</p>}
      {rows.map(row => <div className="coverage-mover" key={row.ticker}><button className="coverage-ticker" onClick={() => onOpenStock(row.ticker)}>{row.ticker}</button><div style={s('height:12px;background:#0b1120;border-radius:3px;overflow:hidden;')}><div style={{ height: '100%', width: Math.abs(row.contribution_bp) / max * 100 + '%', background: positive ? '#267d58' : '#a34c58' }} /></div><span style={{ color: color(row.pct), textAlign: 'right' }}>{pct(row.pct)}</span><span style={s('text-align:right;color:#7e8aa6;font-size:9px;')}>{signed(row.contribution_bp, 0)}BP</span></div>)}</>
  }
  return <section className="coverage-panel" aria-label="Portfolio movers"><div className="coverage-panel-heading"><h2>PORTFOLIO MOVERS</h2><div className="coverage-segments" aria-label="Movers period">{['1W', 'MTD', 'QTD'].map(p => <button key={p} aria-pressed={period === p} onClick={() => setPeriod(p)}>{p}</button>)}</div></div>
    {remote.error ? <Failure title="Movers unavailable" error={remote.error} retry={remote.reload} /> : !data ? <Loading>Loading portfolio movers…</Loading> : <><div className="coverage-muted">{data.fundName}</div>{list(data.contributors, true)}{list(data.detractors, false)}<div className="coverage-rule coverage-muted">{data.startDate || '—'} to {data.asOf || '—'} close. Estimated contribution using current holdings; weights exclude cash.{data.missingTickers.length > 0 && <div style={s('margin-top:6px;')}>{data.missingTickers.length} name(s) omitted for unavailable prices/history: {data.missingTickers.join(', ')}.</div>}</div></>}
  </section>
}
function Watchlist({ onOpenStock }) {
  const [items, setItems] = React.useState(null), [ticker, setTicker] = React.useState('')
  const [error, setError] = React.useState(''), [loadError, setLoadError] = React.useState('')
  const pending = React.useRef(new Set()), generation = React.useRef(0)
  const load = React.useCallback(() => {
    const id = ++generation.current
    setLoadError('')
    getWatchlist().then(data => { if (id === generation.current) setItems(data.items) }).catch(e => { if (id === generation.current) setLoadError(e.detail || e.message) })
  }, [])
  React.useEffect(() => { load(); return () => { generation.current++ } }, [load])
  const add = async e => {
    e.preventDefault()
    const t = ticker.trim().toUpperCase().replaceAll('.', '-')
    if (!t || !items || pending.current.has(t) || items.some(x => x.ticker.replaceAll('.', '-') === t)) return
    generation.current++; pending.current.add(t); setError(''); setTicker('')
    setItems(old => [...old, { ticker: t, pending: true }])
    try { const item = await addWatchlistTicker(t); setItems(old => old.filter(x => x.ticker !== t && x.ticker !== item.ticker).concat(item)) }
    catch (e) { setItems(old => old.filter(x => x.ticker !== t)); setError(e.detail || e.message) }
    finally { pending.current.delete(t) }
  }
  const remove = async item => {
    if (pending.current.has(item.ticker)) return
    generation.current++; pending.current.add(item.ticker); setError('')
    const index = items.findIndex(x => x.ticker === item.ticker)
    setItems(old => old.filter(x => x.ticker !== item.ticker))
    try { await removeWatchlistTicker(item.ticker) }
    catch (e) { setItems(old => { const restored = old.slice(); restored.splice(Math.min(index, old.length), 0, item); return restored }); setError(e.detail || e.message) }
    finally { pending.current.delete(item.ticker) }
  }
  return <section className="coverage-panel" aria-label="Personal watchlist"><div className="coverage-panel-heading"><h2>WATCHLIST</h2><span className="coverage-label">{items?.length || 0} NAMES</span></div>
    <form onSubmit={add} style={s('display:flex;gap:8px;margin:14px 0;')}><input aria-label="Add watchlist ticker" placeholder="Add ticker…" maxLength={24} value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} disabled={!items} /><button disabled={!items || !ticker.trim()}>ADD</button></form>
    {error && <p role="alert" className="coverage-inline-error">{error}</p>}
    {loadError ? <Failure title="Watchlist unavailable" error={loadError} retry={load} /> : !items ? <Loading>Loading your watchlist…</Loading> : <>
      {!items.length && <p className="coverage-muted">Add an equity to follow it here.</p>}
      {items.map(item => <div className="coverage-watch-row" key={item.ticker}><div style={s('display:flex;align-items:baseline;flex-wrap:wrap;justify-content:space-between;gap:6px 12px;')}><div style={s('display:flex;align-items:baseline;gap:8px;min-width:0;flex:1 1 130px;')}><button className="coverage-ticker" disabled={item.pending} onClick={() => onOpenStock(item.ticker)}>{item.ticker}</button><span className="coverage-ellipsis coverage-muted" title={item.name}>{item.pending ? 'Loading…' : item.name}</span></div><div className="coverage-change">{price(item.price)} <span style={{ color: color(item.dayChangePct) }}>{pct(item.dayChangePct)}</span></div></div>
        <div className="coverage-watch-facts"><span>{item.pending ? 'FETCHING QUOTE' : `${money(item.marketCap)} · ${item.rangePct == null ? '—' : item.rangePct.toFixed(0) + '%'} OF 52W RANGE · VOL ${item.volumeRatio == null ? '—' : item.volumeRatio.toFixed(1) + 'x'} AVG`}</span><span>{pe(item.forwardPE)} · {item.nextEarningsEstimated ? '~' : ''}{shortDate(item.nextEarnings)} <button className="coverage-remove" disabled={item.pending} aria-label={`Remove ${item.ticker} from watchlist`} onClick={() => remove(item)}>×</button></span></div>
        {!item.pending && <div className="coverage-caption" style={s('margin-top:5px;')}><span>{item.asOf ? `AS OF ${item.asOf}` : 'QUOTE UNAVAILABLE'}</span></div>}{item.error && <div className="coverage-inline-error">{item.error} <button onClick={load} disabled={pending.current.size > 0}>Retry quotes</button></div>}
      </div>)}
    </>}
  </section>
}
export function MyCoverage({ onOpenStock, auth, fund = 'all', children }) {
  const remote = useRegion(() => getMyCoverage(fund), fund), cards = remote.data?.tickers || []
  const now = new Date(), hour = now.getHours(), greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
  const firstName = auth?.user?.firstName?.trim()
  const nearest = cards.filter(c => c.earningsInDays != null && c.earningsInDays >= 0).sort((a, b) => a.earningsInDays - b.earningsInDays)[0]
  return <div className="my-coverage" style={s('display:flex;flex-wrap:wrap;align-items:stretch;min-width:0;')}><main style={s('flex:1 1 460px;min-width:0;padding:22px 24px 40px;display:flex;flex-direction:column;gap:16px;')}>
    <header style={s('margin-bottom:4px;')}><div className="coverage-label" style={s('color:#5a93f9;letter-spacing:.14em;')}>HOME / MY COVERAGE</div><h1 style={s('font-size:26px;font-weight:600;letter-spacing:-.5px;margin:8px 0 6px;')}>{greeting}{firstName ? `, ${firstName}` : ''}</h1><div style={s('font-size:12.5px;line-height:1.6;color:#7e8aa6;')}>{now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}{remote.data ? ` · ${cards.length} name${cards.length === 1 ? '' : 's'} covered` : ''}{nearest ? ` · next earnings ${nearest.ticker}${nearest.nextEarningsEstimated ? ' (estimated)' : ''} ${nearest.earningsInDays === 0 ? 'today' : `in ${nearest.earningsInDays} days`}` : ''}</div></header>
    {remote.error ? <Failure title="Coverage unavailable" error={remote.error} retry={remote.reload} /> : !remote.data ? <Loading>Loading your coverage…</Loading> : !cards.length ? <div className="coverage-panel"><strong>No coverage assigned yet</strong><p className="coverage-muted">Your sector lead assigns company coverage in the member directory.</p></div> : cards.map(card => <CoverageCard key={card.ticker} card={card} fund={fund} onOpenStock={onOpenStock} />)}{children}
    </main><aside style={s('flex:1 1 340px;min-width:0;border-left:1px solid #1d2840;background:#0a0f1a;padding:22px 20px 40px;display:flex;flex-wrap:wrap;align-content:flex-start;gap:18px;')}><Movers fund={fund} onOpenStock={onOpenStock} /><Watchlist onOpenStock={onOpenStock} /></aside></div>
}
