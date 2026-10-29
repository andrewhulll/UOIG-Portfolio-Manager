import React from 'react'
import { getEarningsCalendar } from '../api.js'
import './earnings.css'

// Earnings calendar for the portfolio manager. The grid answers "when", the
// agenda answers "who, and how much of the fund is that". Weight is the signal:
// every chip carries the position's share of the fund, so a 5% name reporting
// reads differently from a 0.3% one. The API only knows each holding's NEXT
// report plus the last one it stored, so the calendar covers the past week and
// the next six months.

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'] // workweek only
const MODES = [['week', 'Week'], ['month', 'Month'], ['quarter', 'Quarter']]
const BIG = 3 // % of fund at which a position counts as large

const noon = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12)
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, 12)
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const fromIso = (s) => new Date(s + 'T12:00:00')
const startOfWeek = (d) => addDays(d, -((d.getDay() + 6) % 7)) // Monday
const sameDay = (a, b) => iso(a) === iso(b)
const fmt = (d, opts) => d.toLocaleDateString('en-US', opts)
// "Today" is Pacific time everywhere, matching the API, so a late-evening visit
// doesn't flip the calendar to tomorrow.
const todayPT = () => fromIso(new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Los_Angeles' }).format(new Date()))
const surprise = (v) => (v == null ? '' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(1) + '%')
const pct = (w) => (w == null ? '' : w < 0.05 ? '<0.1%' : w.toFixed(1) + '%')

function monthGrid(d) {
  const start = startOfWeek(new Date(d.getFullYear(), d.getMonth(), 1, 12))
  return Array.from({ length: 42 }, (_, i) => addDays(start, i)).filter((d) => d.getDay() % 6 !== 0)
}

// First and last day shown by a view.
function rangeOf(mode, anchor) {
  if (mode === 'week') { const a = startOfWeek(anchor); return [a, addDays(a, 4)] }
  if (mode === 'month') return [new Date(anchor.getFullYear(), anchor.getMonth(), 1, 12), new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0, 12)]
  const q0 = Math.floor(anchor.getMonth() / 3) * 3
  return [new Date(anchor.getFullYear(), q0, 1, 12), new Date(anchor.getFullYear(), q0 + 3, 0, 12)]
}

function shift(mode, anchor, dir) {
  if (mode === 'week') return addDays(anchor, 7 * dir)
  return new Date(anchor.getFullYear(), anchor.getMonth() + (mode === 'month' ? 1 : 3) * dir, 1, 12)
}

function heading(mode, anchor) {
  const [a, b] = rangeOf(mode, anchor)
  if (mode === 'month') return fmt(anchor, { month: 'long', year: 'numeric' })
  if (mode === 'quarter') return `Q${Math.floor(anchor.getMonth() / 3) + 1} ${anchor.getFullYear()}`
  return a.getMonth() === b.getMonth()
    ? `${fmt(a, { month: 'long' })} ${a.getDate()}–${b.getDate()}, ${b.getFullYear()}`
    : `${fmt(a, { month: 'short', day: 'numeric' })} – ${fmt(b, { month: 'short', day: 'numeric', year: 'numeric' })}`
}

function Chip({ e, onOpen, wide }) {
  const cls = 'ec-chip' + (e.estimated ? ' est' : '') + (e.weight >= BIG ? ' big' : '') + (e.past ? ' past' : '')
  const result = e.past && e.epsActual ? `\nReported ${e.epsActual} vs ${e.epsEst || '—'} expected (${surprise(e.surprise)})` : ''
  const tip = `${e.name}${e.sector ? ' · ' + e.sector : ''}${result}${e.reportDate ? '\nReports ' + fmt(fromIso(e.reportDate), { weekday: 'long', month: 'short', day: 'numeric' }) : ''}\n${e.estimated ? 'Projected from the last report, one quarter later' : 'Date from Yahoo Finance; companies can move it'}`
  return (
    <button type="button" className={cls} title={tip} onClick={(ev) => { ev.stopPropagation(); onOpen(e.ticker) }}>
      <span className="ec-tk">{e.ticker}</span>
      {wide && <span className="ec-nm">{e.name}</span>}
      <span className="ec-wt">{pct(e.weight)}</span>
    </button>
  )
}

export function EarningsCalendar({ fund, fundLabel, onOpenStock, onBack }) {
  const [mode, setMode] = React.useState('week')
  const [anchor, setAnchor] = React.useState(() => todayPT())
  const [selected, setSelected] = React.useState(null) // iso day filtering the agenda
  const [query, setQuery] = React.useState('')
  const [state, setState] = React.useState({ status: 'loading' })
  const today = React.useMemo(() => todayPT(), [])

  React.useEffect(() => {
    let live = true
    setState({ status: 'loading' })
    getEarningsCalendar(fund, 180, 7)
      .then((res) => live && setState({ status: 'ok', events: res.events || [] }))
      .catch(() => live && setState({ status: 'error' }))
    return () => { live = false }
  }, [fund])

  const events = React.useMemo(() => {
    const q = query.trim().toLowerCase()
    const all = state.events || []
    const list = q ? all.filter((e) => (e.ticker + ' ' + e.name + ' ' + (e.sector || '')).toLowerCase().includes(q)) : all
    // Biggest positions first within a day.
    return [...list].sort((a, b) => a.date.localeCompare(b.date) || (b.weight || 0) - (a.weight || 0) || a.ticker.localeCompare(b.ticker))
  }, [state.events, query])

  const byDay = React.useMemo(() => {
    const m = {}
    for (const e of events) (m[e.date] = m[e.date] || []).push(e)
    return m
  }, [events])

  const [from, to] = rangeOf(mode, anchor)
  const inRange = events.filter((e) => e.date >= iso(from) && e.date <= iso(to))
  const agenda = selected ? inRange.filter((e) => e.date === selected) : inRange
  const exposure = inRange.reduce((t, e) => t + (e.weight || 0), 0)
  const unconfirmed = inRange.filter((e) => e.estimated).length
  const reportedN = inRange.filter((e) => e.past).length

  const move = (dir) => { setAnchor(shift(mode, anchor, dir)); setSelected(null) }
  const goToday = () => { setAnchor(todayPT()); setSelected(null) }
  const setView = (m) => { setMode(m); setSelected(null) }
  const pick = (d) => { setAnchor(d); setSelected(iso(d)) }

  // ← / → step the view, T jumps to today — unless the filter box has focus.
  const keys = React.useRef()
  keys.current = { move, goToday }
  React.useEffect(() => {
    const on = (ev) => {
      if (ev.target && /input|textarea|select/i.test(ev.target.tagName)) return
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return
      if (ev.key === 'ArrowLeft') keys.current.move(-1)
      else if (ev.key === 'ArrowRight') keys.current.move(1)
      else if (ev.key === 't' || ev.key === 'T') keys.current.goToday()
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [])

  const dayCell = (d, inMonth) => {
    const key = iso(d), evs = byDay[key] || []
    const cls = 'ec-day' + (inMonth ? '' : ' out') + (sameDay(d, today) ? ' today' : '') + (selected === key ? ' sel' : '')
    return (
      <div key={key} className={cls} onClick={() => pick(d)}>
        <span className="ec-num">{d.getDate()}</span>
        {evs.slice(0, 3).map((e) => <Chip key={e.ticker} e={e} onOpen={onOpenStock} />)}
        {evs.length > 3 && <span className="ec-more">{evs.length - 3} more</span>}
      </div>
    )
  }

  let grid = null
  if (mode === 'month') {
    grid = (
      <>
        <div className="ec-wk">{WEEKDAYS.map((w) => <span key={w}>{w}</span>)}</div>
        <div className="ec-month">{monthGrid(anchor).map((d) => dayCell(d, d.getMonth() === anchor.getMonth()))}</div>
      </>
    )
  } else if (mode === 'week') {
    const start = startOfWeek(anchor)
    grid = (
      <div className="ec-weekgrid">
        {Array.from({ length: 5 }, (_, i) => addDays(start, i)).map((d) => {
          const key = iso(d), evs = byDay[key] || []
          return (
            <div key={key} className={'ec-col' + (sameDay(d, today) ? ' today' : '') + (selected === key ? ' sel' : '') + (evs.length ? '' : ' empty')} onClick={() => pick(d)}>
              <div className="ec-colhead"><span>{WEEKDAYS[d.getDay() - 1]}</span><span className="ec-num">{d.getDate()}</span></div>
              {evs.map((e) => <Chip key={e.ticker} e={e} onOpen={onOpenStock} wide />)}
              {!evs.length && <span className="ec-none">No reports</span>}
            </div>
          )
        })}
      </div>
    )
  } else {
    const q0 = Math.floor(anchor.getMonth() / 3) * 3
    grid = (
      <div className="ec-quarter">
        {[0, 1, 2].map((i) => {
          const m = new Date(anchor.getFullYear(), q0 + i, 1, 12)
          return (
            <div key={i} className="ec-mini">
              <button type="button" className="ec-minititle" onClick={() => { setAnchor(m); setMode('month'); setSelected(null) }}>{fmt(m, { month: 'long' })}</button>
              <div className="ec-minigrid">
                {WEEKDAYS.map((w) => <span key={w} className="ec-miniwk">{w[0]}</span>)}
                {monthGrid(m).map((d) => {
                  const key = iso(d), evs = byDay[key] || [], inM = d.getMonth() === m.getMonth()
                  const w = evs.reduce((t, e) => t + (e.weight || 0), 0)
                  const shade = evs.length ? Math.min(0.18 + w * 0.04, 0.6) : 0
                  return (
                    <button type="button" key={key} disabled={!inM}
                      className={'ec-md' + (sameDay(d, today) ? ' today' : '') + (inM ? '' : ' out')}
                      style={{ background: inM && shade ? `rgba(90,147,249,${shade})` : undefined }}
                      title={evs.length ? evs.map((e) => e.ticker).join(', ') : undefined}
                      onClick={() => { setAnchor(d); setMode('month'); setSelected(key) }}>
                      <span>{d.getDate()}</span>
                      {inM && evs.length > 0 && <i>{evs.length}</i>}
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    )
  }

  // Agenda grouped by day.
  const groups = []
  for (const e of agenda) {
    const last = groups[groups.length - 1]
    if (last && last.date === e.date) last.items.push(e); else groups.push({ date: e.date, items: [e] })
  }
  const rangeLabel = mode === 'week' ? 'this week' : mode === 'month' ? 'this month' : 'this quarter'
  const summary = state.status !== 'ok' ? '' : !inRange.length
    ? `No reports ${query ? 'match' : 'expected'} ${rangeLabel}.`
    : `${inRange.length} report${inRange.length === 1 ? '' : 's'} ${rangeLabel}, ${exposure.toFixed(1)}% of ${fundLabel}` +
      (reportedN ? `, ${reportedN} already reported` : '') + (unconfirmed ? `. ${unconfirmed} date${unconfirmed === 1 ? ' is' : 's are'} estimated.` : '.')

  return (
    <div className="ec">
      <button type="button" className="ec-back" onClick={onBack}>‹ Dashboard</button>
      <div className="ec-top">
        <div>
          <h1 className="ec-h1">Earnings calendar</h1>
          <p className="ec-sum">{summary || ' '}</p>
        </div>
        <input className="ec-filter" type="search" value={query} onChange={(e) => { setQuery(e.target.value); setSelected(null) }}
          placeholder="Filter by ticker, name or sector" aria-label="Filter earnings" />
      </div>
      <div className="ec-bar">
        <div className="ec-nav">
          <button type="button" className="ec-btn" onClick={goToday} title="Jump to today (T)">Today</button>
          <button type="button" className="ec-btn sq" onClick={() => move(-1)} aria-label="Previous" title="Previous (←)">‹</button>
          <button type="button" className="ec-btn sq" onClick={() => move(1)} aria-label="Next" title="Next (→)">›</button>
          <span className="ec-range">{heading(mode, anchor)}</span>
        </div>
        <div className="ec-seg" role="tablist">
          {MODES.map(([k, label]) => (
            <button type="button" role="tab" aria-selected={mode === k} key={k} className={mode === k ? 'on' : ''} onClick={() => setView(k)}>{label}</button>
          ))}
        </div>
      </div>
      <div className="ec-body">
        <div className="ec-cal">
          {state.status === 'error' ? <p className="ec-msg">Couldn't load earnings dates. Refresh to try again.</p>
            : state.status === 'loading' ? <p className="ec-msg">Loading earnings dates…</p> : grid}
        </div>
        <aside className="ec-agenda" aria-label="Reports in view">
          <div className="ec-agendain">
          <div className="ec-agendahead">
            <span>{selected ? fmt(fromIso(selected), { weekday: 'long', month: 'short', day: 'numeric' }) : 'In view'}</span>
            {selected && <button type="button" className="ec-clear" onClick={() => setSelected(null)}>Show all</button>}
          </div>
          {groups.map((g) => (
            <div key={g.date} className="ec-group">
              {!selected && <div className="ec-gdate">{fmt(fromIso(g.date), { weekday: 'short', month: 'short', day: 'numeric' })}{g.date === iso(today) ? ' · today' : ''}</div>}
              {g.items.map((e) => (
                <button type="button" key={e.ticker} className={'ec-row' + (e.past ? ' past' : '')} onClick={() => onOpenStock(e.ticker)}>
                  <span className="ec-tk">{e.ticker}</span>
                  <span className="ec-nm">{e.name}</span>
                  {e.past && e.surprise != null && <span className={'ec-surp ' + (e.surprise >= 0 ? 'up' : 'dn')} title={`Reported ${e.epsActual} vs ${e.epsEst || '—'} expected`}>{surprise(e.surprise)}</span>}
                  {e.reportDate && <span className="ec-estlabel" title="Reports on a weekend; shown on the next trading day">{fmt(fromIso(e.reportDate), { weekday: 'short', month: 'short', day: 'numeric' })}</span>}
                  {e.estimated && <span className="ec-estlabel" title="Projected one quarter after the last report">est.</span>}
                  <span className="ec-wt">{pct(e.weight)}</span>
                </button>
              ))}
            </div>
          ))}
          {!groups.length && state.status === 'ok' && <p className="ec-msg small">{selected ? 'No reports on this day.' : 'Nothing to show for this period.'}</p>}
          </div>
        </aside>
      </div>
      <p className="ec-foot">Weights are each position's share of {fundLabel}. Dated reports come from Yahoo Finance, and companies can still move them. A dashed outline or “est.” means Yahoo has no upcoming date yet, so it is projected one quarter after the last report. Reports from the past week are dimmed, with the EPS result against expectations. Weekend reports appear on the next trading day. Only each holding's next and most recent reports are tracked. Keys: ← → to move, T for today.</p>
    </div>
  )
}
