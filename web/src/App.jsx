import React from 'react'
import { Analytics } from '@vercel/analytics/react'
import { getData, getSeries, getFundSeries, getSectorSeries, getStock, getPredictions, getThesis, postChat, runAgent, getAgentRun, searchTickers, getQuote, getHolders, getOptimizeDiagnostics, getOptimizeWhatif, postOptimizeSolve, getMe, logout } from './api.js'
import AuthScreen from './auth/AuthScreen.jsx'
import { LoadingScreen, ErrorScreen } from './StatusScreens.jsx'
import { ProfilePage, PreferencesPage, OrganizationPage } from './profile/SettingsPages.jsx'
import { MyCoverage } from './coverage/MyCoverage.jsx'
import { InboxPage, NewsList, WeeklySubmission } from './submissions/Submissions.jsx'
import { s } from './ui.js'

// UOIG sector taxonomy: the five groups the club uses, each rolling up one or
// more yfinance GICS sectors. Order here is the board's column order.
const SECTOR_GROUPS = [
  { name: 'TMT', color: '#5a93f9', members: ['Technology', 'Communication Services'] },
  { name: 'IME', color: '#f4a531', members: ['Industrials', 'Utilities', 'Basic Materials', 'Energy'] },
  { name: 'Healthcare', color: '#21d07a', members: ['Healthcare'] },
  { name: 'Financial', color: '#c06fd6', members: ['Financial Services', 'Real Estate'] },
  { name: 'Consumer', color: '#e8674c', members: ['Consumer Defensive', 'Consumer Cyclical'] },
]
const SECTOR_OF = {}
SECTOR_GROUPS.forEach((g) => g.members.forEach((m) => (SECTOR_OF[m] = g)))
const GROUP_COLOR = {}
SECTOR_GROUPS.forEach((g) => (GROUP_COLOR[g.name] = g.color))

// s() (CSS-string -> React style object) and the C palette live in ./ui.js.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
function fmtChartDate(d) {
  if (!d) return ''
  const p = String(d).split('-')
  if (p.length < 3) return String(d)
  return MONTHS[(+p[1]) - 1] + ' ' + (+p[2]) + ', ' + p[0]
}
// Compact x-axis date: "Jun 27" for sub-year windows, "Jun '25" when the range spans years.
function fmtAxisDate(d, longSpan) {
  if (!d) return ''
  const p = String(d).split('-')
  if (p.length < 3) return String(d)
  return longSpan ? MONTHS[(+p[1]) - 1] + " '" + p[0].slice(2) : MONTHS[(+p[1]) - 1] + ' ' + (+p[2])
}
// Catmull-Rom -> cubic Bézier: turns a list of [x,y] points into a smooth path.
// Shared by every chart in the terminal so they all curve the same way.
function smoothPath(pts) {
  if (pts.length < 3) return pts.map((p, i) => (i ? 'L' : 'M') + p[0] + ',' + p[1]).join(' ')
  const f = 0.16  // smoothing strength (≈1/6 = classic Catmull-Rom)
  let d = 'M' + pts[0][0] + ',' + pts[0][1]
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2
    const c1x = p1[0] + (p2[0] - p0[0]) * f, c1y = p1[1] + (p2[1] - p0[1]) * f
    const c2x = p2[0] - (p3[0] - p1[0]) * f, c2y = p2[1] - (p3[1] - p1[1]) * f
    d += ' C' + c1x.toFixed(2) + ',' + c1y.toFixed(2) + ' ' + c2x.toFixed(2) + ',' + c2y.toFixed(2) + ' ' + p2[0] + ',' + p2[1]
  }
  return d
}

// Interactive single-line price chart with a price axis and a hover readout.
// Used on the stock page (the fund/hero charts still use App._chart).
function PriceChart({ dates, values, color, height }) {
  const [hover, setHover] = React.useState(null)
  const wrapRef = React.useRef(null)
  const n = values ? values.length : 0
  if (!n) return React.createElement('div', { style: { height: height + 'px' } })

  const W = 900, padT = 6, padB = 6, plotH = height - padT - padB
  const min = Math.min.apply(null, values)
  const max = Math.max.apply(null, values)
  const span = (max - min) || 1
  const Y = (v) => +(height - padB - ((v - min) / span) * plotH).toFixed(2)
  const X = (i) => +((i / ((n - 1) || 1)) * W).toFixed(2)
  const xPct = (i) => (i / ((n - 1) || 1)) * 100

  const line = smoothPath(values.map((v, i) => [X(i), Y(v)]))
  const area = line + ' L' + W + ',' + height + ' L0,' + height + ' Z'
  const gid = 'pc-grad-' + (color || '').replace('#', '')

  const TN = 4
  const ticks = []
  for (let k = 0; k <= TN; k++) {
    const val = min + (span * k) / TN
    ticks.push({ val, y: Y(val) })
  }

  const onMove = (e) => {
    const r = wrapRef.current && wrapRef.current.getBoundingClientRect()
    if (!r || !r.width) return
    let idx = Math.round(((e.clientX - r.left) / r.width) * (n - 1))
    idx = Math.max(0, Math.min(n - 1, idx))
    setHover(idx)
  }

  const fmtPrice = (v) => '$' + v.toFixed(2)
  const gridY = (f) => +(padT + plotH * f).toFixed(1)

  const svg = React.createElement('svg', {
    key: 'svg',
    viewBox: '0 0 ' + W + ' ' + height, preserveAspectRatio: 'none',
    style: { width: '100%', height: '100%', display: 'block' },
  }, [
    React.createElement('defs', { key: 'defs' }, [
      React.createElement('linearGradient', { key: 'g', id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, [
        React.createElement('stop', { key: 'a', offset: '0', style: { stopColor: color, stopOpacity: 0.26 } }),
        React.createElement('stop', { key: 'b', offset: '1', style: { stopColor: color, stopOpacity: 0 } }),
      ]),
    ]),
  ].concat(ticks.map((t, i) => React.createElement('line', {
    key: 'grid' + i, x1: 0, y1: t.y, x2: W, y2: t.y, style: { stroke: '#16203a', strokeWidth: 1 },
  }))).concat([
    React.createElement('path', { key: 'area', d: area, style: { fill: 'url(#' + gid + ')', stroke: 'none' } }),
    React.createElement('path', { key: 'line', d: line, style: { fill: 'none', stroke: color, strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' } }),
  ]))

  // axis gutter: price labels aligned to the grid lines
  const axis = React.createElement('div', {
    key: 'axis',
    style: { position: 'relative', width: '52px', flex: '0 0 auto', height: height + 'px' },
  }, ticks.map((t, i) => React.createElement('span', {
    key: 'ax' + i,
    style: {
      position: 'absolute', right: 0, top: t.y + 'px', transform: 'translateY(-50%)',
      fontFamily: "'IBM Plex Mono'", fontSize: '9.5px', color: '#6b7794', whiteSpace: 'nowrap',
    },
  }, fmtPrice(t.val))))

  // hover overlay: crosshair, marker dot, and a price/date tooltip
  let overlay = []
  if (hover != null && hover < n) {
    const left = xPct(hover)
    const topY = Y(values[hover])
    const clamped = Math.max(11, Math.min(89, left))
    overlay = [
      React.createElement('div', {
        key: 'cross',
        style: { position: 'absolute', top: 0, bottom: 0, left: left + '%', width: '1px', background: 'rgba(154,167,194,.35)', pointerEvents: 'none' },
      }),
      React.createElement('div', {
        key: 'dot',
        style: { position: 'absolute', left: left + '%', top: topY + 'px', width: '8px', height: '8px', borderRadius: '50%', background: color, border: '2px solid #0e1422', transform: 'translate(-50%,-50%)', pointerEvents: 'none' },
      }),
      React.createElement('div', {
        key: 'tip',
        style: { position: 'absolute', left: clamped + '%', top: Math.max(0, topY - 50) + 'px', transform: 'translateX(-50%)', background: '#0a0f1a', border: '1px solid #24345a', borderRadius: '6px', padding: '5px 9px', pointerEvents: 'none', whiteSpace: 'nowrap', boxShadow: '0 4px 14px rgba(0,0,0,.45)' },
      }, [
        React.createElement('div', { key: 'p', style: { fontFamily: "'IBM Plex Mono'", fontSize: '12px', color: '#e8edf7' } }, fmtPrice(values[hover])),
        React.createElement('div', { key: 'd', style: { fontFamily: "'IBM Plex Mono'", fontSize: '9.5px', color: '#7e8aa6', marginTop: '2px' } }, fmtChartDate(dates && dates[hover])),
      ]),
    ]
  }

  const plot = React.createElement('div', {
    key: 'plot', ref: wrapRef, onMouseMove: onMove, onMouseLeave: () => setHover(null),
    style: { position: 'relative', flex: '1 1 auto', minWidth: 0, height: height + 'px', cursor: 'crosshair' },
  }, [svg].concat(overlay))

  return React.createElement('div', { style: { display: 'flex', alignItems: 'stretch', height: height + 'px' } }, [plot, axis])
}

// Interactive multi-line indexed-return chart (sector page): a % y-axis, a date
// x-axis, and a hover readout listing the date plus every series (our holdings +
// each iShares index). Each `series` is {label, color, values, area?} where
// values are indexed to 100 at the period start (so % change = value - 100).
function IndexChart({ dates, series, height }) {
  const [hover, setHover] = React.useState(null)
  const wrapRef = React.useRef(null)
  const lines = (series || []).filter((s2) => s2.values && s2.values.length)
  if (!lines.length) return React.createElement('div', { style: { height: height + 'px' } })

  const W = 900, padT = 8, padB = 8, axisH = 18
  const plotH = height - axisH, innerH = plotH - padT - padB
  let min = Infinity, max = -Infinity
  lines.forEach((s2) => s2.values.forEach((v) => { if (v < min) min = v; if (v > max) max = v }))
  if (!(max > min)) { min -= 1; max += 1 }
  const span = (max - min) || 1
  const Y = (v) => +(plotH - padB - ((v - min) / span) * innerH).toFixed(2)
  const xAt = (i, n) => +((i / ((n - 1) || 1)) * W).toFixed(2)
  const path = (vals) => smoothPath(vals.map((v, i) => [xAt(i, vals.length), Y(v)]))

  const TN = 4, ticks = []
  for (let k = 0; k <= TN; k++) { const val = min + (span * k) / TN; ticks.push({ val, y: Y(val) }) }
  const fmtPct = (v) => (v - 100 >= 0 ? '+' : '') + (v - 100).toFixed(1) + '%'

  const nd = (dates && dates.length) || 0
  const longSpan = nd > 1 && String(dates[0]).slice(0, 4) !== String(dates[nd - 1]).slice(0, 4)
  const xticks = []
  if (nd) for (let k = 0; k <= 4; k++) { const i = Math.round(k / 4 * (nd - 1)); xticks.push({ f: i / ((nd - 1) || 1), d: dates[i] }) }

  const onMove = (e) => {
    const r = wrapRef.current && wrapRef.current.getBoundingClientRect()
    if (!r || !r.width) return
    setHover(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)))
  }

  const gid = 'ic-grad-' + (lines[0].color || '').replace('#', '')
  const svgKids = [React.createElement('defs', { key: 'defs' }, [
    React.createElement('linearGradient', { key: 'g', id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, [
      React.createElement('stop', { key: 'a', offset: '0', style: { stopColor: lines[0].color, stopOpacity: 0.22 } }),
      React.createElement('stop', { key: 'b', offset: '1', style: { stopColor: lines[0].color, stopOpacity: 0 } }),
    ]),
  ])]
  ticks.forEach((t, i) => svgKids.push(React.createElement('line', { key: 'g' + i, x1: 0, y1: t.y, x2: W, y2: t.y, style: { stroke: Math.abs(t.val - 100) < 1e-6 ? '#26324d' : '#16203a', strokeWidth: 1 } })))
  lines.forEach((s2, li) => {
    const d = path(s2.values)
    if (s2.area) svgKids.push(React.createElement('path', { key: 'ar' + li, d: d + ' L' + W + ',' + plotH + ' L0,' + plotH + ' Z', style: { fill: 'url(#' + gid + ')', stroke: 'none' } }))
    svgKids.push(React.createElement('path', { key: 'ln' + li, d, style: { fill: 'none', stroke: s2.color, strokeWidth: s2.area ? 2 : 1.5, strokeLinecap: 'round', strokeLinejoin: 'round' } }))
  })
  const svg = React.createElement('svg', { key: 'svg', viewBox: '0 0 ' + W + ' ' + plotH, preserveAspectRatio: 'none', style: { width: '100%', height: plotH + 'px', display: 'block' } }, svgKids)

  const axis = React.createElement('div', { key: 'axis', style: { position: 'relative', width: '50px', flex: '0 0 auto', height: plotH + 'px' } },
    ticks.map((t, i) => React.createElement('span', { key: 'ax' + i, style: { position: 'absolute', right: 0, top: t.y + 'px', transform: 'translateY(-50%)', fontFamily: "'IBM Plex Mono'", fontSize: '9.5px', color: '#6b7794', whiteSpace: 'nowrap' } }, fmtPct(t.val))))

  let overlay = []
  if (hover != null) {
    const leftPct = hover * 100
    const rows = lines.map((s2) => { const idx = Math.max(0, Math.min(s2.values.length - 1, Math.round(hover * (s2.values.length - 1)))); return { label: s2.label, color: s2.color, val: s2.values[idx], y: Y(s2.values[idx]) } })
    const di = Math.max(0, Math.min(nd - 1, Math.round(hover * (nd - 1))))
    const clamped = Math.max(15, Math.min(85, leftPct))
    overlay.push(React.createElement('div', { key: 'cross', style: { position: 'absolute', top: 0, height: plotH + 'px', left: leftPct + '%', width: '1px', background: 'rgba(154,167,194,.35)', pointerEvents: 'none' } }))
    rows.forEach((rw, i) => overlay.push(React.createElement('div', { key: 'dot' + i, style: { position: 'absolute', left: leftPct + '%', top: rw.y + 'px', width: '7px', height: '7px', borderRadius: '50%', background: rw.color, border: '2px solid #0e1422', transform: 'translate(-50%,-50%)', pointerEvents: 'none' } })))
    overlay.push(React.createElement('div', { key: 'tip', style: { position: 'absolute', left: clamped + '%', top: '2px', transform: 'translateX(-50%)', background: '#0a0f1a', border: '1px solid #24345a', borderRadius: '6px', padding: '6px 9px', pointerEvents: 'none', whiteSpace: 'nowrap', boxShadow: '0 4px 14px rgba(0,0,0,.45)' } }, [
      React.createElement('div', { key: 'd', style: { fontFamily: "'IBM Plex Mono'", fontSize: '9.5px', color: '#7e8aa6', marginBottom: '4px' } }, fmtChartDate(dates && dates[di])),
    ].concat(rows.map((rw, i) => React.createElement('div', { key: 'r' + i, style: { display: 'flex', alignItems: 'center', gap: '6px', marginTop: i ? '2px' : 0 } }, [
      React.createElement('span', { key: 'sw', style: { width: '7px', height: '7px', borderRadius: '50%', background: rw.color, flex: '0 0 auto' } }),
      React.createElement('span', { key: 'lb', style: { fontFamily: "'IBM Plex Sans'", fontSize: '10px', color: '#9aa7c2' } }, rw.label),
      React.createElement('span', { key: 'vl', style: { fontFamily: "'IBM Plex Mono'", fontSize: '10px', color: '#e8edf7', marginLeft: '14px' } }, fmtPct(rw.val)),
    ])))))
  }

  const plot = React.createElement('div', { key: 'plot', ref: wrapRef, onMouseMove: onMove, onMouseLeave: () => setHover(null), style: { position: 'relative', flex: '1 1 auto', minWidth: 0, height: plotH + 'px', cursor: 'crosshair' } }, [svg].concat(overlay))
  const chartRow = React.createElement('div', { key: 'row', style: { display: 'flex', alignItems: 'stretch', height: plotH + 'px' } }, [plot, axis])
  const dateRow = React.createElement('div', { key: 'dates', style: { display: 'flex', height: axisH + 'px' } }, [
    React.createElement('div', { key: 'dx', style: { position: 'relative', flex: '1 1 auto', minWidth: 0 } }, xticks.map((t, i) => React.createElement('span', {
      key: 'd' + i, style: { position: 'absolute', left: (t.f * 100) + '%', top: '3px', transform: i === 0 ? 'translateX(0)' : (i === xticks.length - 1 ? 'translateX(-100%)' : 'translateX(-50%)'), fontFamily: "'IBM Plex Mono'", fontSize: '9px', color: '#5d6a85', whiteSpace: 'nowrap' },
    }, fmtAxisDate(t.d, longSpan)))),
    React.createElement('div', { key: 'sp', style: { width: '50px', flex: '0 0 auto' } }),
  ])
  return React.createElement('div', { style: { height: height + 'px' } }, [chartRow, dateRow])
}

export default class App extends React.Component {
  constructor(props) {
    super(props)
    this.mainRef = React.createRef()
    this.chatRef = React.createRef()
    let preferences = {}
    try { preferences = JSON.parse(localStorage.getItem('uoig.preferences') || '{}') } catch (_) { /* ignore invalid local state */ }
    const landing = ['dashboard', 'stocks', 'sectors', 'optimize'].includes(preferences.landingPage) ? preferences.landingPage : 'dashboard'
    this.state = {
      auth: 'loading',  // 'loading' | { user, role, canInvite } | null (signed out)
      profileOpen: false,  // profile menu popover
      avatarImgFailed: false,  // fall back to initials if the Google photo 404s
      data: null, error: null,
      view: landing, fund: preferences.defaultFund || (typeof localStorage !== 'undefined' && localStorage.getItem('uoig.fund')) || 'all', period: preferences.defaultPeriod || 'YTD',
      preferences,
      ticker: null, sector: null, prevView: 'dashboard',
      stkTab: 'overview', chatOpen: false,
      sortKey: 'w', sortDir: 'desc', query: '',
      chat: [], input: '', loading: false, agentBusy: false,
      series: {},  // cache: key -> {dates, values/close, ...}
      sectorSeries: {},  // cache: `${group}:${period}` -> {sector, benchmarks, movers} | 'loading' | 'error'
      sectorPeriod: '1M',  // sector comparison chart window (independent of the global period)
      stkDetail: {},  // cache: ticker -> {financials, earnings, news, research} | 'loading' | 'error'
      predictions: {},  // cache: ticker -> {cards} | 'loading' | 'error'
      theses: {},  // cache: ticker -> {thesis} | 'loading' | 'error'
      quotes: {},  // cache: ticker -> overview {t,n,s,px,...} | 'loading' | 'error' (off-portfolio names)
      holders: {},  // cache: ticker -> [{holder,pct,shares,value}] | 'loading' | 'error' (top institutional)
      optimizeFund: null,  // selected fund key on the Optimize page (defaults to first fund)
      optimizeTab: 'diagnostics',  // diagnostics | whatif | optimizer
      optimizeDiag: {},  // cache: fundKey -> diagnostics payload | 'loading' | 'error'
      whatif: {},  // cache: fundKey -> whatif payload (cov, weights) | 'loading' | 'error'
      whatifAdj: {},  // fundKey -> {ticker: adjusted weight %} (slider state)
      whatifDest: 'overlay',  // where trim proceeds go: 'overlay' | 'cash'
      optResult: {},  // cache: fundKey -> BL solve result | 'loading' | 'error'
      optViews: {},  // fundKey -> {ticker: {q: str, conf: 'low'|'med'|'high'}}
      optCap: '10', optErp: '5',  // optimizer constraint inputs (% strings)
      searchQ: '', searchResults: [], searchOpen: false, searchActive: -1,
    }
    this._searchSeq = 0
  }

  componentDidMount() {
    // Gate on sign-in first; only load portfolio data once authenticated. AuthScreen
    // (rendered when auth is null) owns the sign-in / invite / reset URL handling.
    getMe()
      .then((me) => {
        // Analysts land on their coverage by default (unless they've picked an
        // explicit landing page in Preferences); admins/leadership keep the dashboard.
        const view = (me.role === 'member' && !this.state.preferences.landingPage)
          ? 'coverage' : this.state.view
        this.setState({ auth: me, view })
        this._loadData()
      })
      .catch(() => this.setState({ auth: null }))
    // Re-render once a minute so the markets-open badge and date stay current.
    this._clock = setInterval(() => this.forceUpdate(), 30000)
    // Poll live prices while the market is open (backend refreshes quotes on a
    // background thread; everything else is nightly). No-op when closed.
    this._dataPoll = setInterval(() => {
      if (this.state.auth && this.state.data && this._marketStatus().open) this._refreshData()
    }, 45000)
  }

  componentWillUnmount() {
    if (this._clock) clearInterval(this._clock)
    if (this._dataPoll) clearInterval(this._dataPoll)
  }

  // Refetch portfolio data in place (live prices) without resetting the view —
  // only the `data` slice changes, so the selected fund/tab/series are preserved.
  _refreshData() {
    getData().then((data) => this.setState({ data })).catch(() => {})
  }

  // Live market status in US Eastern time (handles EST/EDT). NYSE regular
  // session runs Mon–Fri 9:30 AM–4:00 PM ET; markets are closed otherwise.
  // (Holidays are not accounted for.)
  _marketStatus() {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', weekday: 'short', hourCycle: 'h23',
      hour: '2-digit', minute: '2-digit', year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(new Date()).reduce((a, p) => (a[p.type] = p.value, a), {})
    const weekday = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].indexOf(parts.weekday) >= 0
    const mins = (+parts.hour) * 60 + (+parts.minute)
    const open = weekday && mins >= 9 * 60 + 30 && mins < 16 * 60
    return { open, date: `${parts.year}-${parts.month}-${parts.day}` }
  }

  _loadData() {
    if (this.state.data) return
    getData()
      .then((data) => {
        const keys = Object.keys(data.funds)
        const fund = ['all', ...keys].includes(this.state.fund) ? this.state.fund : 'all'
        this.setState({ data, fund }, this._ensureSeries)
      })
      .catch(() => this.setState({ error: 'Could not reach the API. Is the backend running on :8000?' }))
  }

  _signOut() {
    logout().catch(() => {}).then(() => this.setState({ auth: null, data: null, profileOpen: false }))
  }

  // Initials for the header avatar, from the signed-in user (falls back to 'PM').
  _userInitials() {
    const u = (this.state.auth && this.state.auth.user) || null
    if (!u) return 'PM'
    const parts = (u.name || `${u.firstName || ''} ${u.lastName || ''}`).trim().split(/\s+/).filter(Boolean)
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
    return (u.email || 'PM').slice(0, 2).toUpperCase()
  }

  // Round avatar: Google photo if present (initials fallback on missing/broken image).
  _avatar(px, fontPx) {
    const u = (this.state.auth && this.state.auth.user) || {}
    const base = `width:${px}px;height:${px}px;border-radius:50%;border:1px solid #24345a;flex:0 0 auto;`
    if (u.profilePictureUrl && !this.state.avatarImgFailed) {
      return <img src={u.profilePictureUrl} alt="" onError={() => this.setState({ avatarImgFailed: true })} style={s(base + 'object-fit:cover;')} />
    }
    return <div style={s(base + `background:#13203a;display:flex;align-items:center;justify-content:center;font:600 ${fontPx}px 'IBM Plex Sans';color:#9aa7c2;`)}>{this._userInitials()}</div>
  }

  _renderProfileMenu() {
    const a = this.state.auth || {}
    const u = a.user || {}
    const roleName = a.role === 'member' ? 'Analyst' : a.role === 'sector-leader' ? 'Sector Leader' : (a.role || 'Member')
    const open = (view) => this.setState({ view, profileOpen: false })
    return (
      <>
        <div onClick={() => this.setState({ profileOpen: false })} style={s('position:fixed;inset:0;z-index:90;')}></div>
        <div style={s('position:fixed;right:12px;top:56px;width:276px;background:#0e1422;border:1px solid #1d2840;border-radius:12px;box-shadow:0 20px 56px rgba(0,0,0,.6);z-index:91;overflow:hidden;')}>
          <div style={s('display:flex;align-items:center;gap:11px;padding:15px;border-bottom:1px solid #1d2840;')}>
            {this._avatar(38, 13)}
            <div style={s('min-width:0;')}>
              <div style={s("font:600 13px 'IBM Plex Sans';color:#e8edf7;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")}>{u.name || u.email || 'Signed in'}</div>
              <div style={s("font:400 11px 'IBM Plex Mono';color:#6b7794;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")}>{u.email || ''}</div>
            </div>
          </div>
          <div style={s('padding:10px 15px;border-bottom:1px solid #1d2840;display:flex;align-items:center;justify-content:space-between;')}><span style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.07em;text-transform:uppercase;color:#6b7794;")}>UOIG member</span><span style={s("font:600 9px 'IBM Plex Sans';letter-spacing:.04em;text-transform:uppercase;color:#5a93f9;background:#13203a;border:1px solid #28406e;border-radius:5px;padding:3px 8px;")}>{roleName}</span></div>
          <div style={s('padding:6px 0;border-bottom:1px solid #1d2840;')}>
            {[
              ['profile', '○', 'My profile', 'Identity and account details'],
              ['preferences', '⚙', 'Preferences', 'Startup and display options'],
              ['organization', '◎', 'Organization', 'Members and company coverage'],
            ].map(([view, icon, title, subtitle]) => <button key={view} onClick={() => open(view)} className="dc-hover" style={s("width:100%;border:0;background:transparent;display:grid;grid-template-columns:22px 1fr auto;align-items:center;gap:8px;padding:10px 15px;cursor:pointer;text-align:left;color:#cdd6e8;font-family:'IBM Plex Sans';")}><span style={s('font-size:14px;color:#7283a4;')}>{icon}</span><span><span style={s('display:block;font-size:11.5px;font-weight:500;')}>{title}</span><small style={s('display:block;font-size:9px;color:#59657e;margin-top:2px;')}>{subtitle}</small></span><span style={s('color:#53617c;')}>›</span></button>)}
          </div>
          <div onClick={() => this._signOut()} className="dc-hover" style={s("display:flex;align-items:center;gap:9px;padding:12px 15px;cursor:pointer;font:500 12px 'IBM Plex Sans';color:#cdd6e8;")}>
            <svg width="14" height="14" viewBox="0 0 16 16" style={{ fill: 'none', stroke: '#9aa7c2', strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round' }}><path d="M6 14H3.5A1.5 1.5 0 0 1 2 12.5v-9A1.5 1.5 0 0 1 3.5 2H6"></path><path d="M10.5 11 14 7.5 10.5 4"></path><path d="M14 7.5H6"></path></svg>
            Sign out
          </div>
        </div>
      </>
    )
  }

  componentDidUpdate(_p, prev) {
    if (prev.view !== this.state.view && this.mainRef.current) this.mainRef.current.scrollTop = 0
    if (prev.view !== this.state.view || prev.fund !== this.state.fund ||
        prev.period !== this.state.period || prev.ticker !== this.state.ticker) this._ensureSeries()
    if (prev.stkTab !== this.state.stkTab || prev.view !== this.state.view ||
        prev.ticker !== this.state.ticker) { this._ensurePredictions(); this._ensureThesis() }
    if (this.state.view === 'stock' &&
        (prev.view !== 'stock' || prev.ticker !== this.state.ticker)) this._ensureHolders()
    if (this.state.view === 'sector' &&
        (prev.view !== 'sector' || prev.sector !== this.state.sector ||
         prev.sectorPeriod !== this.state.sectorPeriod)) this._ensureSectorSeries()
    if (this.state.view === 'optimize') {
      const optCtx = prev.view !== 'optimize' || prev.optimizeFund !== this.state.optimizeFund ||
                     prev.optimizeTab !== this.state.optimizeTab
      if (optCtx) {
        this._ensureOptimizeDiag()
        if (this.state.optimizeTab === 'whatif') this._ensureWhatif()
        if (this.state.optimizeTab === 'optimizer') { this._ensureWhatif(); this._ensureOptSolve() }
      }
    }
    const pl = (prev.chat && prev.chat.length) || 0
    if (this.chatRef.current && (pl !== this.state.chat.length || prev.loading !== this.state.loading))
      this.chatRef.current.scrollTop = this.chatRef.current.scrollHeight
  }

  // ---------- data shaping ----------
  get funds() {
    const out = {}
    const f = this.state.data.funds
    Object.keys(f).forEach((k) => {
      const c = { ...f[k] }
      c.ret = Object.fromEntries(Object.entries(f[k].ret || {}).map(([p, v]) => [p, (v || 0) * 100]))
      c.bret = Object.fromEntries(Object.entries(f[k].bret || {}).map(([p, v]) => [p, (v || 0) * 100]))
      c.tag = f[k].name.split(' ').map((w) => w[0]).join('').slice(0, 3).toUpperCase()
      out[k] = c
    })
    return out
  }
  get fundKeys() { return Object.keys(this.state.data.funds) }
  get allH() { return this.state.data.holdings }
  get byT() { const m = {}; this.allH.forEach((h) => (m[h.t] = h)); return m }
  get total() { return this.fundKeys.reduce((s2, k) => s2 + (this.funds[k].aum || 0), 0) }

  _blend(getter) {
    const t = this.total || 1
    return this.fundKeys.reduce((s2, k) => s2 + (getter(this.funds[k]) || 0) * (this.funds[k].aum || 0), 0) / t
  }
  // Map a yfinance GICS sector to its UOIG group name (null for ETFs/unmapped).
  _group(sector) { return (SECTOR_OF[sector] || {}).name || null }

  _aggSectors(fk) {
    const all = !fk || fk === 'all'
    const pool = all ? this.allH : this.allH.filter((h) => h.fund === fk)
    const agg = {}
    pool.forEach((h) => {
      const g = SECTOR_OF[h.s]
      if (!g) return  // ETFs / unmapped sectors are not part of the five groups
      const a = agg[g.name] || (agg[g.name] = { name: g.name, color: g.color, members: g.members, count: 0, holdings: [], wSum: 0, wret: 0, wByFund: {} })
      a.count++; a.holdings.push(h); a.wSum += h.w; a.wret += h.w * h.mtd
      a.wByFund[h.fund] = (a.wByFund[h.fund] || 0) + h.w
    })
    Object.values(agg).forEach((a) => {
      a.ret = a.wSum ? a.wret / a.wSum : 0
      if (all) {
        // blended share of the whole endowment by dollars
        a.dollar = this.fundKeys.reduce((s2, k) => s2 + (a.wByFund[k] || 0) / 100 * this.funds[k].aum, 0)
        a.share = this.total ? a.dollar / this.total * 100 : 0
      } else {
        // share relative to the selected fund (its weight within that fund)
        a.dollar = (a.wByFund[fk] || 0) / 100 * this.funds[fk].aum
        a.share = a.wSum
      }
    })
    return agg
  }
  _fundSectors(fk) {
    const hs = fk === 'all' ? this.allH : this.allH.filter((h) => h.fund === fk)
    const m = {}; let tot = 0
    hs.forEach((h) => { const g = SECTOR_OF[h.s]; if (!g) return; m[g.name] = (m[g.name] || 0) + h.w; tot += h.w })
    return Object.keys(m).map((name) => ({ name, w: m[name], pct: tot ? m[name] / tot * 100 : 0 }))
      .sort((a, b) => b.w - a.w)
  }

  // ---------- formatting ----------
  _num(n) { return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
  // Fund/holding dollar amounts: billions ≥ $1B ($1.20B), millions ≥ $1M ($2.74M), else thousands ($93K). Input is USD.
  _kd(dollars) {
    const d = Number(dollars) || 0, a = Math.abs(d)
    if (a >= 1e9) return '$' + (d / 1e9).toFixed(2) + 'B'
    if (a >= 1e6) return '$' + (d / 1e6).toFixed(2) + 'M'
    return '$' + Math.round(d / 1000).toLocaleString('en-US') + 'K'
  }
  _kdSigned(dollars) {
    const d = Number(dollars) || 0, a = Math.abs(d), sign = d >= 0 ? '+' : '-'
    if (a >= 1e9) return sign + '$' + (a / 1e9).toFixed(2) + 'B'
    if (a >= 1e6) return sign + '$' + (a / 1e6).toFixed(2) + 'M'
    return sign + '$' + Math.round(a / 1000).toLocaleString('en-US') + 'K'
  }
  _sign(x, d) { return (x >= 0 ? '+' : '') + Number(x).toFixed(d === undefined ? 2 : d) }
  _col(x) { return x >= 0 ? '#21d07a' : '#ff5666' }

  // ---------- navigation ----------
  _go(view) { this.setState({ view, profileOpen: false }) }
  _setFund(k) { try { localStorage.setItem('uoig.fund', k) } catch (e) { /* ignore */ } this.setState({ fund: k }) }
  _openStock(t, from) {
    const tk = (t || '').toUpperCase()
    this.setState({ view: 'stock', ticker: tk, prevView: from || this.state.view, stkTab: 'overview' },
      () => this._ensureQuote(tk))
  }
  _openSector(name, from) { this.setState({ view: 'sector', sector: name, prevView: from || this.state.view }) }

  // ---------- global search (Yahoo Finance + local holdings) ----------
  _localMatches(q) {
    if (!this.state.data) return []
    const s2 = q.trim().toLowerCase()
    if (!s2) return []
    const seen = new Set(), out = []
    this.allH.forEach((h) => {
      if (seen.has(h.t)) return
      if (h.t.toLowerCase().includes(s2) || (h.n || '').toLowerCase().includes(s2)) {
        seen.add(h.t)
        out.push({ symbol: h.t, name: h.n, exchange: (this.funds[h.fund] || {}).name || '', held: true })
      }
    })
    return out.slice(0, 6)
  }
  _onSearchChange(q) {
    const local = this._localMatches(q)
    this.setState({ searchQ: q, searchOpen: true, searchActive: -1, searchResults: local })
    const seq = ++this._searchSeq
    clearTimeout(this._searchTimer)
    if (!q.trim()) return
    this._searchTimer = setTimeout(() => {
      searchTickers(q).then((res) => {
        if (seq !== this._searchSeq) return  // a newer keystroke superseded this one
        const have = new Set(local.map((r) => r.symbol))
        const remote = (res.results || []).filter((r) => !have.has(r.symbol)).map((r) => ({ ...r, remote: true }))
        this.setState({ searchResults: [...local, ...remote] })
      }).catch(() => {})
    }, 180)
  }
  _searchSelect(symbol) {
    if (!symbol) return
    this._searchSeq++  // invalidate any in-flight search
    clearTimeout(this._searchTimer)
    this.setState({ searchOpen: false, searchQ: '', searchResults: [], searchActive: -1 })
    this._openStock(symbol, this.state.view)
  }
  _searchKey(e) {
    const { searchResults, searchActive, searchOpen } = this.state
    if (e.key === 'Escape') { this.setState({ searchOpen: false, searchActive: -1 }); return }
    if (!searchOpen || !searchResults.length) {
      if (e.key === 'Enter' && this.state.searchQ.trim()) this._searchSelect(this.state.searchQ.trim().toUpperCase())
      return
    }
    if (e.key === 'ArrowDown') { e.preventDefault(); this.setState({ searchActive: Math.min(searchActive + 1, searchResults.length - 1) }) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); this.setState({ searchActive: Math.max(searchActive - 1, 0) }) }
    else if (e.key === 'Enter') {
      e.preventDefault()
      const pick = searchActive >= 0 ? searchResults[searchActive] : searchResults[0]
      if (pick) this._searchSelect(pick.symbol)
      else if (this.state.searchQ.trim()) this._searchSelect(this.state.searchQ.trim().toUpperCase())
    }
  }

  // ---------- series fetching ----------
  _ensureSeries() {
    if (!this.state.data) return
    const { view, fund, period, ticker } = this.state
    const need = []
    if (view === 'dashboard') need.push(['fund', fund, period])
    if (view === 'stock' && ticker) {
      need.push(['stk', ticker, period])
      const f = this.byT[ticker]; if (f) need.push(['fund', f.fund, period])
    }
    need.forEach(([kind, id, per]) => {
      const key = `${kind}:${id}:${per}`
      if (this.state.series[key]) return
      const p = kind === 'stk' ? getSeries(id, per)
        : id === 'all' ? Promise.all(this.fundKeys.map((k) => getFundSeries(k, per))).then((arr) => ({ multi: arr }))
          : getFundSeries(id, per)
      p.then((res) => this.setState((st) => ({ series: { ...st.series, [key]: res } }))).catch(() => {})
    })
    this._ensureStockDetail()
    if (this.state.view === 'stock') this._ensureQuote()
  }

  // Sector page: value-weighted sector index + iShares benchmarks + weekly movers.
  // Always the trailing one month (the page's comparison window), cached per group.
  _ensureSectorSeries() {
    const g = this.state.sector, per = this.state.sectorPeriod
    if (!g) return
    const key = `${g}:${per}`
    if (this.state.sectorSeries[key]) return
    this.setState((st) => ({ sectorSeries: { ...st.sectorSeries, [key]: 'loading' } }))
    getSectorSeries(g, per)
      .then((res) => this.setState((st) => ({ sectorSeries: { ...st.sectorSeries, [key]: res } })))
      .catch(() => this.setState((st) => ({ sectorSeries: { ...st.sectorSeries, [key]: 'error' } })))
  }

  // ---------- stock-detail tabs (live yfinance) ----------
  _ensureStockDetail() {
    const { view, ticker } = this.state
    if (view !== 'stock' || !ticker || this.state.stkDetail[ticker]) return
    this.setState((st) => ({ stkDetail: { ...st.stkDetail, [ticker]: 'loading' } }))
    getStock(ticker)
      .then((res) => this.setState((st) => ({ stkDetail: { ...st.stkDetail, [ticker]: res } })))
      .catch(() => this.setState((st) => ({ stkDetail: { ...st.stkDetail, [ticker]: 'error' } })))
  }

  // Predictions are a separate, heavier Kalshi pull — fetch only when that tab is opened.
  _ensurePredictions() {
    const { view, ticker, stkTab } = this.state
    if (view !== 'stock' || stkTab !== 'predictions' || !ticker || this.state.predictions[ticker]) return
    this.setState((st) => ({ predictions: { ...st.predictions, [ticker]: 'loading' } }))
    getPredictions(ticker)
      .then((res) => this.setState((st) => ({ predictions: { ...st.predictions, [ticker]: res } })))
      .catch(() => this.setState((st) => ({ predictions: { ...st.predictions, [ticker]: 'error' } })))
  }

  // Off-portfolio tickers have no holding row — pull a live overview so the
  // stock page (price, snapshot, business) can render. Held names use the DB.
  _ensureQuote(t) {
    const tk = t || this.state.ticker
    if (!tk || (this.state.data && this.byT[tk])) return
    if (this.state.quotes[tk]) return
    this.setState((st) => ({ quotes: { ...st.quotes, [tk]: 'loading' } }))
    getQuote(tk)
      .then((res) => this.setState((st) => ({ quotes: { ...st.quotes, [tk]: res } })))
      .catch(() => this.setState((st) => ({ quotes: { ...st.quotes, [tk]: 'error' } })))
  }

  // Top institutional shareholders (yfinance 13F) for the stock overview.
  _ensureHolders(t) {
    const tk = t || this.state.ticker
    if (!tk || this.state.holders[tk]) return
    this.setState((st) => ({ holders: { ...st.holders, [tk]: 'loading' } }))
    getHolders(tk)
      .then((res) => this.setState((st) => ({ holders: { ...st.holders, [tk]: res.holders || [] } })))
      .catch(() => this.setState((st) => ({ holders: { ...st.holders, [tk]: 'error' } })))
  }

  // Per-fund optimization diagnostics (active risk vs benchmark) for the Optimize page.
  _ensureOptimizeDiag() {
    const key = this.state.optimizeFund || (this.fundKeys && this.fundKeys[0])
    if (!key || this.state.optimizeDiag[key]) return
    this.setState((st) => ({ optimizeDiag: { ...st.optimizeDiag, [key]: 'loading' } }))
    getOptimizeDiagnostics(key)
      .then((res) => this.setState((st) => ({ optimizeDiag: { ...st.optimizeDiag, [key]: res } })))
      .catch(() => this.setState((st) => ({ optimizeDiag: { ...st.optimizeDiag, [key]: 'error' } })))
  }

  // What-if sandbox inputs (covariance + weights) — the client recomputes risk live.
  _ensureWhatif() {
    const key = this.state.optimizeFund || (this.fundKeys && this.fundKeys[0])
    if (!key || this.state.whatif[key]) return
    this.setState((st) => ({ whatif: { ...st.whatif, [key]: 'loading' } }))
    getOptimizeWhatif(key)
      .then((res) => this.setState((st) => ({ whatif: { ...st.whatif, [key]: res } })))
      .catch(() => this.setState((st) => ({ whatif: { ...st.whatif, [key]: 'error' } })))
  }

  // Black-Litterman solve. Auto-runs once per fund (implied returns, no views);
  // the Solve button re-runs with the club's views and constraints.
  _ensureOptSolve() {
    const key = this.state.optimizeFund || (this.fundKeys && this.fundKeys[0])
    if (!key || this.state.optResult[key]) return
    this._runSolve(key)
  }

  _runSolve(k) {
    const key = k || this.state.optimizeFund || (this.fundKeys && this.fundKeys[0])
    if (!key) return
    const vmap = this.state.optViews[key] || {}
    const views = Object.entries(vmap)
      .filter(([, v]) => v && v.q !== '' && !isNaN(parseFloat(v.q)))
      .map(([t, v]) => ({ t, q: parseFloat(v.q), conf: v.conf || 'med' }))
    const body = { views, max_pos: parseFloat(this.state.optCap) || 10, erp: parseFloat(this.state.optErp) || 5 }
    this.setState((st) => ({ optResult: { ...st.optResult, [key]: 'loading' } }))
    postOptimizeSolve(key, body)
      .then((res) => this.setState((st) => ({ optResult: { ...st.optResult, [key]: res } })))
      .catch(() => this.setState((st) => ({ optResult: { ...st.optResult, [key]: 'error' } })))
  }

  // Ex-ante portfolio stats from the shipped covariance — mirrors the backend's
  // math exactly (verified equal) so slider moves recompute instantly client-side.
  // w: stock weight fractions (payload order), o: overlay fraction, cash: fraction.
  _wfStats(d, w, o, cash) {
    const n = w.length, cov = d.cov
    const x = w.concat([-(1 - o)])   // active-return coefficients (bench last)
    const y = w.concat([o])          // total-return coefficients
    let te2 = 0, v2 = 0, cb = 0
    const sx = new Array(n + 1).fill(0)
    for (let i = 0; i <= n; i++) {
      let sxi = 0, syi = 0
      for (let j = 0; j <= n; j++) { sxi += cov[i][j] * x[j]; syi += cov[i][j] * y[j] }
      sx[i] = sxi
      te2 += x[i] * sxi; v2 += y[i] * syi
      if (i < n) cb += w[i] * cov[i][n]
    }
    const varB = cov[n][n] || 1
    const beta = (cb + o * varB) / varB
    // Look-through active share (+ cash counts as an active bet)
    let heldAbs = 0, heldBench = 0
    for (let i = 0; i < n; i++) { heldAbs += Math.abs(w[i] - (1 - o) * d.stocks[i].bench_w); heldBench += d.stocks[i].bench_w }
    const as = 0.5 * (heldAbs + (1 - o) * Math.max((d.bench_total || 1) - heldBench, 0) + Math.max(cash, 0)) * 100
    // Per-stock share of active variance (signed; bench row omitted)
    const rc = []
    for (let i = 0; i < n; i++) rc.push(te2 > 0 ? (x[i] * sx[i]) / te2 * 100 : 0)
    return { te: Math.sqrt(Math.max(te2, 0)) * 100, vol: Math.sqrt(Math.max(v2, 0)) * 100, beta, as, rc }
  }

  _ensureThesis() {
    const { view, ticker, stkTab } = this.state
    if (view !== 'stock' || stkTab !== 'thesis' || !ticker || this.state.theses[ticker]) return
    this.setState((st) => ({ theses: { ...st.theses, [ticker]: 'loading' } }))
    getThesis(ticker)
      .then((res) => this.setState((st) => ({ theses: { ...st.theses, [ticker]: res } })))
      .catch(() => this.setState((st) => ({ theses: { ...st.theses, [ticker]: 'error' } })))
  }

  // ---------- charts ----------
  _chart(key, lines, h) {
    const w = 900, all = []
    lines.forEach((l) => l.values.forEach((v) => all.push(v)))
    if (!all.length) all.push(0, 1)
    const min = Math.min.apply(null, all), max = Math.max.apply(null, all), span = (max - min) || 1
    const Y = (v) => +(h - 6 - ((v - min) / span) * (h - 12)).toFixed(2)
    const X = (i, n) => +((i / ((n - 1) || 1)) * w).toFixed(2)
    const grid = [0.16, 0.40, 0.66, 0.92].map((f, gi) =>
      React.createElement('line', { key: 'g' + gi, x1: 0, y1: +(h * f).toFixed(1), x2: w, y2: +(h * f).toFixed(1), style: { stroke: '#16203a', strokeWidth: 1 } }))
    const defs = [], paths = []
    lines.forEach((l, li) => {
      const n = l.values.length; if (!n) return
      const d = smoothPath(l.values.map((v, i) => [X(i, n), Y(v)]))
      if (l.area) {
        const gid = key + '-g' + li
        defs.push(React.createElement('linearGradient', { key: 'd' + li, id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, [
          React.createElement('stop', { key: 'a', offset: '0', style: { stopColor: l.color, stopOpacity: 0.26 } }),
          React.createElement('stop', { key: 'b', offset: '1', style: { stopColor: l.color, stopOpacity: 0 } }),
        ]))
        paths.push(React.createElement('path', { key: 'ar' + li, d: d + (' L' + w + ',' + h + ' L0,' + h + ' Z'), style: { fill: 'url(#' + gid + ')', stroke: 'none' } }))
      }
      paths.push(React.createElement('path', { key: 'ln' + li, d, style: { fill: 'none', stroke: l.color, strokeWidth: l.width || 2, strokeDasharray: l.dash || 'none', strokeLinecap: 'round', strokeLinejoin: 'round' } }))
    })
    return React.createElement('svg', { viewBox: '0 0 ' + w + ' ' + h, preserveAspectRatio: 'none', style: { width: '100%', height: h + 'px', display: 'block' } },
      [React.createElement('defs', { key: 'defs' }, defs)].concat(grid).concat(paths))
  }
  _donut(arr) {
    const cols = ['#5a93f9', '#6aa6ff', '#8ea8f2', '#21d07a', '#f4a531', '#c06fd6']
    const top = arr.slice(0, 5), other = arr.slice(5).reduce((s2, x) => s2 + x.pct, 0)
    const segs = top.map((x, i) => ({ c: x.color || cols[i], pct: x.pct })); if (other > 0.1) segs.push({ c: '#3a4a6a', pct: other })
    let acc = 0
    const stops = segs.map((sg) => { const a = acc, b = acc + sg.pct; acc = b; return sg.c + ' ' + a.toFixed(1) + '% ' + b.toFixed(1) + '%' }).join(', ')
    return React.createElement('div', { style: { width: '108px', height: '108px', borderRadius: '50%', background: 'conic-gradient(' + stops + ')', position: 'relative', flex: '0 0 auto' } },
      React.createElement('div', { style: { position: 'absolute', inset: '17px', borderRadius: '50%', background: '#0e1422', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' } }, [
        React.createElement('span', { key: 'a', style: { fontFamily: "'IBM Plex Mono'", fontSize: '16px', color: '#e8edf7' } }, String(arr.length)),
        React.createElement('span', { key: 'b', style: { fontSize: '8px', color: '#6b7794', textTransform: 'uppercase', letterSpacing: '.06em' } }, 'sectors'),
      ]))
  }
  _icon(name, active) {
    const mk = (children, fill) => React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 16 16', style: fill ? { fill: 'currentColor' } : { fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round' } }, children)
    if (name === 'dash') return mk([React.createElement('rect', { key: 1, x: 1, y: 1, width: 6, height: 6, rx: 1 }), React.createElement('rect', { key: 2, x: 9, y: 1, width: 6, height: 6, rx: 1 }), React.createElement('rect', { key: 3, x: 1, y: 9, width: 6, height: 6, rx: 1 }), React.createElement('rect', { key: 4, x: 9, y: 9, width: 6, height: 6, rx: 1 })], true)
    if (name === 'funds') return mk([React.createElement('rect', { key: 1, x: 1, y: 8, width: 3.4, height: 7, rx: 1 }), React.createElement('rect', { key: 2, x: 6.3, y: 4, width: 3.4, height: 11, rx: 1 }), React.createElement('rect', { key: 3, x: 11.6, y: 1, width: 3.4, height: 14, rx: 1 })], true)
    if (name === 'stocks') return mk([React.createElement('polyline', { key: 1, points: '1,11 5.5,6.5 9,9 15,2.5' })], false)
    if (name === 'sectors') return mk([React.createElement('circle', { key: 1, cx: 8, cy: 8, r: 6, style: { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8 } }), React.createElement('path', { key: 2, d: 'M8 2 A6 6 0 0 1 13.2 8 L8 8 Z', style: { fill: 'currentColor', stroke: 'none' } })], false)
    if (name === 'optimize') return mk([React.createElement('line', { key: 1, x1: 3, y1: 2, x2: 3, y2: 14 }), React.createElement('line', { key: 2, x1: 8, y1: 2, x2: 8, y2: 14 }), React.createElement('line', { key: 3, x1: 13, y1: 2, x2: 13, y2: 14 }), React.createElement('circle', { key: 4, cx: 3, cy: 5, r: 1.6, style: { fill: 'currentColor' } }), React.createElement('circle', { key: 5, cx: 8, cy: 10, r: 1.6, style: { fill: 'currentColor' } }), React.createElement('circle', { key: 6, cx: 13, cy: 6, r: 1.6, style: { fill: 'currentColor' } })], false)
    if (name === 'assistant') return mk([React.createElement('path', { key: 1, d: 'M8 1.4 L9.5 6.2 L14.6 8 L9.5 9.8 L8 14.6 L6.5 9.8 L1.4 8 L6.5 6.2 Z' })], true)
    if (name === 'coverage') return mk([React.createElement('circle', { key: 1, cx: 8, cy: 8, r: 6.4 }), React.createElement('circle', { key: 2, cx: 8, cy: 8, r: 1.6, style: { fill: 'currentColor', stroke: 'none' } })], false)
    return null
  }

  // ---------- claude (stub via /api/chat) ----------
  _fmt(text) {
    return String(text).split('\n').map((ln, li) => (
      <span key={li}>
        {ln.split(/(\*\*[^*]+\*\*)/g).map((p, pi) => /^\*\*[^*]+\*\*$/.test(p)
          ? <b key={pi} style={{ color: '#fff', fontWeight: 600 }}>{p.slice(2, -2)}</b> : p)}
        {li < String(text).split('\n').length - 1 ? <br /> : null}
      </span>
    ))
  }
  _chatContext() {
    const st = this.state
    if (st.view === 'stock' && this.byT[st.ticker]) { const h = this.byT[st.ticker]; return h.t + ' — ' + h.n + ' (' + h.s + ', ' + (this.funds[h.fund] || {}).name + ')' }
    if (st.view === 'sector') return 'the ' + st.sector + ' sector'
    const f = st.fund === 'all' ? 'both funds combined' : (this.funds[st.fund] || {}).name
    return st.view + ' view · ' + f + ' · ' + st.period
  }
  async _send(text) {
    const q = (text != null ? text : this.state.input).trim()
    if (!q || this.state.loading) return
    const ctx = this._chatContext()
    const chat = this.state.chat.concat([{ role: 'user', content: q }])
    this.setState({ chat, input: '', loading: true, chatOpen: true })
    try {
      const res = await postChat(chat, ctx)
      this.setState((st) => ({ chat: st.chat.concat([{ role: 'assistant', content: res.reply || '(no response)' }]), loading: false }))
    } catch (e) {
      this.setState((st) => ({ chat: st.chat.concat([{ role: 'assistant', content: '⚠ Could not reach the assistant.' }]), loading: false }))
    }
  }

  // Trigger the Anthropic Managed Agent (market analysis). The run takes ~30s, so
  // the backend kicks it off in the background and we poll for the result — no long
  // request to time out. Output drops into the chat when ready.
  _runAgent() {
    if (this.state.agentBusy || this.state.loading) return
    this.setState((st) => ({ chatOpen: true, loading: true, agentBusy: true,
      chat: st.chat.concat([{ role: 'user', content: '▶ Run market analysis' }]) }))
    const finish = (content) => this.setState((st) => ({ loading: false, agentBusy: false,
      chat: st.chat.concat([{ role: 'assistant', content }]) }))
    runAgent()
      .then((res) => {
        if (!res || !res.job_id) { finish('⚠ Could not start the agent run.'); return }
        let tries = 0
        const poll = () => {
          if (++tries > 150) { finish('⚠ The agent run timed out.'); return }  // ~6 min cap
          getAgentRun(res.job_id)
            .then((j) => {
              if (j.status === 'done') finish(j.reply || 'The agent returned no output.')
              else if (j.status === 'error') finish('⚠ The agent run failed: ' + (j.error || 'unknown error'))
              else setTimeout(poll, 2500)
            })
            .catch(() => finish('⚠ Lost contact with the agent run.'))
        }
        setTimeout(poll, 2500)
      })
      .catch((e) => finish(String(e).includes('503')
        ? '⚠ The market-analysis agent isn’t configured on the backend yet.'
        : '⚠ Could not start the agent run.'))
  }

  _rowVM(h, from) {
    const ctb = (h.w / 100) * h.mtd
    const fund = this.funds[h.fund] || {}
    return {
      t: h.t, rk: (h.fund || '') + ':' + h.t, n: h.n, s: h.s, fundTag: fund.tag || h.fund, fundColor: fund.color || '#5a93f9',
      wStr: h.w.toFixed(1) + '%', pxStr: this._num(h.px), mvStr: this._kd(h.mv),
      dayStr: this._sign(h.chg) + '%', dayColor: this._col(h.chg),
      mtdStr: this._sign(h.mtd, 1) + '%', mtdColor: this._col(h.mtd),
      peStr: h.pe ? h.pe.toFixed(1) : '—',
      ctbStr: this._sign(ctb, 2), ctbColor: this._col(ctb),
      open: () => this._openStock(h.t, from),
    }
  }


  render() {
    // Auth gate — the entire terminal renders only for signed-in users.
    if (this.state.auth === 'loading') return <LoadingScreen label="Authenticating…" />
    if (!this.state.auth) return <AuthScreen onAuthenticated={(me) => { this.setState({ auth: me }); this._loadData() }} />
    if (this.state.error) return <ErrorScreen title="Couldn't load the terminal" message="We reached the server but couldn't load your portfolio data. This is usually temporary — give it another try." actions={[{ label: 'Retry', onClick: () => this.setState({ error: null, data: null }, () => this._loadData()), primary: true }, { label: 'Sign out', onClick: () => this._signOut() }]} />
    if (!this.state.data) return <LoadingScreen label="Loading terminal…" />
    const v = this.renderVals()
    const F = this.funds
    return (
      <div data-reduced-motion={String(!!this.state.preferences.reducedMotion)} data-density={this.state.preferences.density || 'comfortable'} style={s("height:100vh;width:100%;display:flex;flex-direction:column;background:#070a12;color:#e8edf7;font-family:'IBM Plex Sans',sans-serif;overflow:hidden;")}>
        {/* HEADER */}
        <div className="app-header" style={s('height:48px;flex:0 0 48px;display:flex;align-items:center;gap:14px;padding:0 16px;background:#0a0f1a;border-bottom:1px solid #1d2840;')}>
          <div className="app-brand" style={s('display:flex;align-items:center;gap:10px;cursor:pointer;')} onClick={() => this._go('dashboard')}>
            <img src="/uoig-logo.png" alt="UOIG" style={s('width:26px;height:26px;object-fit:contain;background:#fff;border-radius:5px;padding:2px;')} />
            <div className="app-brand-name" style={s("font:600 14px 'IBM Plex Sans';color:#e8edf7;")}>University of Oregon Investment Group</div>
          </div>
          <div className="app-header-search" style={s('position:relative;width:320px;margin-left:10px;')}>
            <div style={{ ...s('display:flex;align-items:center;gap:8px;background:#0e1422;border-radius:7px;padding:7px 11px;'), border: '1px solid ' + (this.state.searchOpen ? '#28406e' : '#1d2840') }}>
              <svg width="13" height="13" viewBox="0 0 16 16" style={{ fill: 'none', stroke: '#5d6a85', strokeWidth: 1.6 }}><circle cx="7" cy="7" r="4.5"></circle><line x1="11" y1="11" x2="14.5" y2="14.5" style={{ strokeLinecap: 'round' }}></line></svg>
              <input value={this.state.searchQ} onChange={(e) => this._onSearchChange(e.target.value)}
                onFocus={() => { if (this.state.searchResults.length) this.setState({ searchOpen: true }) }}
                onBlur={() => setTimeout(() => this.setState({ searchOpen: false }), 150)}
                onKeyDown={(e) => this._searchKey(e)}
                placeholder="Search any equity on Yahoo Finance…"
                style={s("flex:1;min-width:0;background:transparent;border:none;outline:none;color:#e8edf7;font:400 11.5px 'IBM Plex Sans';")} />
              <span style={s("font-family:'IBM Plex Mono';font-size:10px;color:#3c465e;border:1px solid #1d2840;border-radius:3px;padding:1px 5px;flex:0 0 auto;")}>↵</span>
            </div>
            {this.state.searchOpen && this.state.searchResults.length > 0 && (
              <div style={s('position:absolute;top:40px;left:0;right:0;background:#0b1120;border:1px solid #1d2840;border-radius:8px;box-shadow:0 16px 40px rgba(0,0,0,.55);overflow:hidden;overflow-y:auto;max-height:360px;z-index:80;')}>
                {this.state.searchResults.map((r, i) => (
                  <div key={r.symbol} onMouseDown={(e) => { e.preventDefault(); this._searchSelect(r.symbol) }}
                    onMouseEnter={() => this.setState({ searchActive: i })}
                    style={{ ...s('display:flex;align-items:center;gap:10px;padding:9px 12px;cursor:pointer;border-bottom:1px solid #131c2f;'), background: i === this.state.searchActive ? '#13203a' : 'transparent' }}>
                    <span style={s("font-family:'IBM Plex Mono';font-weight:600;font-size:12px;color:#e8edf7;width:66px;flex:0 0 auto;overflow:hidden;text-overflow:ellipsis;")}>{r.symbol}</span>
                    <span style={s('flex:1;min-width:0;font-size:11.5px;color:#9aa7c2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;')}>{r.name}</span>
                    <span style={{ ...s("font:600 8px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;border-radius:4px;padding:2px 6px;flex:0 0 auto;"), color: r.held ? '#5a93f9' : '#6b7794', border: '1px solid ' + (r.held ? '#28406e' : '#1d2840') }}>{r.held ? 'Held' : (r.exchange || 'Yahoo')}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="app-fund-tabs" style={s('display:flex;background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:3px;gap:2px;margin-left:10px;')}>
            {v.fundTabs.map((t) => (<span key={t.k} onClick={t.on} style={{ ...s("padding:6px 15px;border-radius:6px;cursor:pointer;font-size:11.5px;font-family:'IBM Plex Sans';"), fontWeight: t.weight, background: t.bg, color: t.color }}>{t.label}</span>))}
          </div>
          <div style={s('flex:1;')}></div>
          <div className="app-market-status" style={s("display:flex;align-items:center;gap:7px;font-family:'IBM Plex Mono';font-size:11px;color:#9aa7c2;")}><span style={{ ...s('width:7px;height:7px;border-radius:50%;'), background: v.marketOpen ? '#21d07a' : '#6b7794', animation: v.marketOpen ? 'pulseDot 2s infinite' : 'none' }}></span>{v.marketOpen ? 'MARKETS OPEN' : 'MARKETS CLOSED'}</div>
          <div className="app-asof" style={s("font-family:'IBM Plex Mono';font-size:11px;color:#6b7794;")}>{v.asOf}</div>
          <div onClick={() => this.setState((st) => ({ profileOpen: !st.profileOpen }))} title={(this.state.auth && this.state.auth.user && (this.state.auth.user.name || this.state.auth.user.email)) || 'Profile'} className="dc-hover" style={s('cursor:pointer;display:flex;')}>{this._avatar(28, 10.5)}</div>
          {this.state.profileOpen && this._renderProfileMenu()}
        </div>

        {/* BODY */}
        <div style={s('flex:1;display:flex;min-height:0;')}>
          {/* NAV RAIL */}
          <div style={s('width:54px;flex:0 0 54px;background:#0a0f1a;border-right:1px solid #1d2840;display:flex;flex-direction:column;align-items:center;padding:12px 0;gap:5px;')}>
            {v.nav.map((item) => (
              <div key={item.key} onClick={item.on} title={item.label} className="dc-hover" style={{ ...s('width:40px;height:38px;border-radius:8px;display:flex;align-items:center;justify-content:center;cursor:pointer;'), background: item.bg, color: item.color }}>{item.icon}</div>
            ))}
          </div>

          {/* MAIN */}
          <div ref={this.mainRef} style={s('flex:1;min-width:0;overflow-y:auto;overflow-x:hidden;')}>
            {v.isDashboard && this._renderDashboard(v)}
            {v.isStocks && this._renderStocks(v)}
            {v.isSectors && this._renderSectors(v)}
            {v.isStock && (v.stk ? this._renderStock(v) : this._renderStockMsg(v))}
            {v.isSector && v.sec && this._renderSector(v)}
            {v.isOptimize && this._renderOptimize(v)}
            {v.isAssistant && this._renderAssistant(v)}
            {this.state.view === 'profile' && <ProfilePage auth={this.state.auth} onNavigate={(view) => this._go(view)} onUserUpdated={(user) => this.setState((st) => ({ auth: { ...st.auth, user }, avatarImgFailed: false }))} />}
            {this.state.view === 'preferences' && <PreferencesPage fundOptions={[{ value: 'all', label: 'All Funds' }, ...this.fundKeys.map(k => ({ value: k, label: this.funds[k].name }))]} currentFund={this.state.fund} currentPeriod={this.state.period} onNavigate={(view) => this._go(view)} onApply={(preferences) => this.setState({ preferences, fund: preferences.defaultFund, period: preferences.defaultPeriod })} />}
            {this.state.view === 'organization' && <OrganizationPage auth={this.state.auth} holdings={this.allH} onNavigate={(view) => this._go(view)} onOpenStock={(ticker) => this._openStock(ticker, 'organization')} />}
            {this.state.view === 'coverage' && <><MyCoverage onOpenStock={(ticker) => this._openStock(ticker, 'coverage')} /><WeeklySubmission auth={this.state.auth} /></>}
            {this.state.view === 'inbox' && <InboxPage auth={this.state.auth} />}
          </div>

        </div>

        {/* ASK-CLAUDE POPUP */}
        {this.state.chatOpen && !['profile', 'preferences', 'organization', 'assistant'].includes(this.state.view) && (
          <div style={s('position:fixed;right:22px;bottom:88px;width:374px;height:560px;max-height:calc(100vh - 120px);background:#0b0d1d;border:1px solid #241f3e;border-radius:16px;box-shadow:0 26px 64px rgba(0,0,0,.55);display:flex;flex-direction:column;overflow:hidden;z-index:60;')}>
            <div style={s('display:flex;align-items:center;justify-content:space-between;padding:13px 14px;border-bottom:1px solid #241f3e;background:linear-gradient(180deg,#140f2c,#0b0d1d);flex:0 0 auto;')}>
              <div style={s("display:flex;align-items:center;gap:8px;font:600 11px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#c3b9ff;")}><span style={s('font-size:15px;')}>✦</span>Ask Claude</div>
              <div style={s('display:flex;align-items:center;gap:7px;')}>
                <span onClick={() => this.setState({ chat: [] })} style={s('font-size:9px;color:#7a6fb5;border:1px solid #2c2550;border-radius:5px;padding:3px 8px;cursor:pointer;')}>CLEAR</span>
                <span onClick={() => this.setState({ chatOpen: false })} style={s('width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:13px;color:#7a6fb5;border:1px solid #2c2550;border-radius:5px;cursor:pointer;')}>✕</span>
              </div>
            </div>
            <div style={s('padding:9px 13px;border-bottom:1px solid #1a1730;display:flex;align-items:center;gap:7px;flex:0 0 auto;')}><span style={s('font-size:8.5px;color:#7a6fb5;text-transform:uppercase;letter-spacing:.06em;')}>Context</span><span style={s('font-size:9.5px;color:#c3b9ff;background:#15112c;border:1px solid #2c2550;border-radius:5px;padding:3px 9px;')}>{v.ctxLabel}</span></div>
            <div ref={this.chatRef} style={s('flex:1;padding:14px 13px;display:flex;flex-direction:column;gap:11px;overflow-y:auto;min-height:0;')}>
              {v.chatEmpty && (
                <div style={s('display:flex;flex-direction:column;align-items:center;text-align:center;gap:8px;margin:auto 0;color:#6b7794;padding:0 6px;')}>
                  <span style={s('font-size:24px;color:#5a4fd6;')}>✦</span>
                  <div style={s("font:600 12.5px 'IBM Plex Sans';color:#b8aef0;")}>Your research co-pilot</div>
                  <div style={s('font-size:11px;line-height:1.55;')}>Ask anything about a fund, holding, or sector — I know the live portfolio.</div>
                </div>
              )}
              {v.chatMsgs.map((m) => (
                <div key={m.key} style={{ ...s('padding:9px 11px;font-size:11.5px;line-height:1.55;white-space:pre-wrap;'), alignSelf: m.align, maxWidth: m.maxw, background: m.bg, border: '1px solid ' + m.border, borderRadius: m.radius, color: m.color }}>{m.body}</div>
              ))}
              {v.loading && (
                <div style={s('align-self:flex-start;display:flex;align-items:center;gap:7px;color:#7a6fb5;font-size:10.5px;')}><span style={s('display:flex;gap:3px;')}><span style={s('width:5px;height:5px;border-radius:50%;background:#7a6fb5;animation:pulseDot 1.4s infinite;')}></span><span style={s('width:5px;height:5px;border-radius:50%;background:#7a6fb5;animation:pulseDot 1.4s infinite .2s;')}></span><span style={s('width:5px;height:5px;border-radius:50%;background:#7a6fb5;animation:pulseDot 1.4s infinite .4s;')}></span></span>Claude is analyzing…</div>
              )}
            </div>
            <div style={s('padding:11px 13px;border-top:1px solid #241f3e;flex:0 0 auto;')}>
              <div onClick={() => this._runAgent()} style={{ ...s("display:flex;align-items:center;justify-content:center;gap:7px;margin-bottom:10px;padding:8px;border-radius:8px;font:600 10.5px 'IBM Plex Sans';letter-spacing:.03em;cursor:pointer;"), background: this.state.agentBusy ? '#1a1533' : 'linear-gradient(135deg,#5a4fd6,#3a31a8)', color: this.state.agentBusy ? '#7a6fb5' : '#fff', cursor: this.state.agentBusy ? 'default' : 'pointer' }}><span style={s('font-size:11px;')}>▶</span>{this.state.agentBusy ? 'Running market analysis…' : 'Run market analysis'}</div>
              <div style={s('display:flex;align-items:flex-end;gap:8px;background:#0a0f1a;border:1px solid #2c2550;border-radius:10px;padding:8px 10px;')}>
                <input value={v.input} onChange={(e) => this.setState({ input: e.target.value })} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._send() } }} placeholder={'Ask about ' + v.ctxShort + '…'} style={s("flex:1;background:transparent;border:none;outline:none;color:#e8edf7;font:400 11.5px 'IBM Plex Sans';")} />
                <span onClick={() => this._send()} style={{ ...s('width:27px;height:27px;border-radius:7px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;cursor:pointer;flex:0 0 auto;'), background: v.sendBg }}>↑</span>
              </div>
            </div>
          </div>
        )}

        {/* ASK-CLAUDE FAB */}
        {!['profile', 'preferences', 'organization', 'assistant'].includes(this.state.view) && <div onClick={() => this.setState((st) => ({ chatOpen: !st.chatOpen }))} title="Ask Claude" style={{ ...s('position:fixed;right:22px;bottom:22px;width:56px;height:56px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;color:#fff;font-size:23px;z-index:61;box-shadow:0 12px 30px rgba(90,79,214,.5);'), background: this.state.chatOpen ? '#2c2550' : 'linear-gradient(135deg,#5a4fd6,#3a31a8)' }}>{this.state.chatOpen ? '✕' : '✦'}</div>}
        <Analytics />
      </div>
    )
  }

  // ---------- view renderers ----------
  _renderDashboard(v) {
    return (
      <div style={s('padding:16px;display:flex;flex-direction:column;gap:13px;')}>
        {/* hero */}
        <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:17px;display:flex;flex-direction:column;')}>
          <div style={s('display:flex;justify-content:space-between;align-items:flex-start;')}>
            <div>
              <div style={s("font:500 10.5px 'IBM Plex Sans';text-transform:uppercase;letter-spacing:.09em;color:#6b7794;")}>{v.heroTitle}</div>
              <div style={s("font-family:'IBM Plex Mono';font-size:36px;font-weight:500;color:#e8edf7;margin-top:5px;letter-spacing:-.01em;")}>{v.heroValue}</div>
              <div style={{ ...s("font-family:'IBM Plex Mono';font-size:13px;margin-top:3px;"), color: v.heroRetColor }}>{v.heroRetText}</div>
            </div>
            <div style={s('display:flex;align-items:center;gap:3px;background:#0a0f1a;border:1px solid #1d2840;border-radius:8px;padding:3px;')}>
              {v.periods.map((p) => (<span key={p.k} onClick={p.on} style={{ ...s("padding:5px 10px;border-radius:5px;cursor:pointer;font-size:10px;font-family:'IBM Plex Mono';"), fontWeight: p.weight, background: p.bg, color: p.color }}>{p.k}</span>))}
            </div>
          </div>
          <div style={s('height:184px;margin-top:10px;')}>{v.heroChartEl}</div>
          <div style={s("display:flex;justify-content:space-between;font-family:'IBM Plex Mono';font-size:9px;color:#4a5573;margin-top:6px;")}>{v.xLabels.map((x, i) => (<span key={i}>{x}</span>))}</div>
        </div>
        {/* stat tiles */}
        <div style={s('display:grid;grid-template-columns:repeat(6,1fr);gap:11px;')}>
          {v.heroStats.map((st2, i) => (
            <div key={i} title={st2.tooltip} style={s('background:#0e1422;border:1px solid #1d2840;border-radius:8px;padding:11px 13px;')}>
              <div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.07em;text-transform:uppercase;color:#6b7794;")}>{st2.l}</div>
              <div style={{ ...s("font-family:'IBM Plex Mono';font-size:19px;margin-top:6px;"), color: st2.c }}>{st2.v}</div>
              <div style={s('font-size:9px;color:#5d6a85;margin-top:2px;')}>{st2.sub}</div>
            </div>
          ))}
        </div>
        {/* lower */}
        <div style={s('display:grid;grid-template-columns:1fr 360px;gap:13px;')}>
          <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;display:flex;flex-direction:column;overflow:hidden;')}>
            <div style={s('display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid #1d2840;')}><span style={s("font:600 10.5px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;")}>{v.dashTitle}</span><span style={s("font-family:'IBM Plex Mono';font-size:9.5px;color:#5d6a85;")}>{v.dashCount}</span></div>
            <div style={s("display:grid;grid-template-columns:62px 1fr 50px 54px 70px 78px 60px 64px;gap:8px;padding:8px 14px;border-bottom:1px solid #1d2840;font:600 8.5px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;color:#6b7794;")}><span>Ticker</span><span>Name</span><span style={s('text-align:right;')}>Fund</span><span style={s('text-align:right;')}>Wt</span><span style={s('text-align:right;')}>Val</span><span style={s('text-align:right;')}>Price</span><span style={s('text-align:right;')}>Day</span><span style={s('text-align:right;')}>Contrib</span></div>
            {v.dashHoldings.map((r) => (
              <div key={r.rk} onClick={r.open} className="dc-row" style={s('display:grid;grid-template-columns:62px 1fr 50px 54px 70px 78px 60px 64px;gap:8px;align-items:center;padding:7.5px 14px;border-bottom:1px solid #131c2f;font-size:11px;cursor:pointer;')}>
                <span style={s("font-family:'IBM Plex Mono';font-weight:600;color:#e8edf7;")}>{r.t}</span>
                <span style={s('color:#9aa7c2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;')}>{r.n}</span>
                <span style={{ ...s("text-align:right;font:500 9px 'IBM Plex Mono';"), color: r.fundColor }}>{r.fundTag}</span>
                <span style={s("font-family:'IBM Plex Mono';text-align:right;color:#cdd6e8;")}>{r.wStr}</span>
                <span style={s("font-family:'IBM Plex Mono';text-align:right;color:#e8edf7;")}>{r.mvStr}</span>
                <span style={s("font-family:'IBM Plex Mono';text-align:right;color:#cdd6e8;")}>{r.pxStr}</span>
                <span style={{ ...s("font-family:'IBM Plex Mono';text-align:right;"), color: r.dayColor }}>{r.dayStr}</span>
                <span style={{ ...s("font-family:'IBM Plex Mono';text-align:right;"), color: r.ctbColor }}>{r.ctbStr}</span>
              </div>
            ))}
            <div onClick={() => this._go('stocks')} className="dc-row" style={s("padding:9px 14px;border-top:1px solid #1d2840;font-family:'IBM Plex Mono';font-size:9.5px;color:#5a93f9;text-align:center;cursor:pointer;")}>{v.dashMoreText}</div>
          </div>
          <div style={s('display:flex;flex-direction:column;gap:13px;')}>
            <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:13px;')}>
              <div style={s("font:600 9.5px 'IBM Plex Sans';letter-spacing:.09em;text-transform:uppercase;color:#7e8aa6;margin-bottom:11px;")}>Sector Mix</div>
              <div style={s('display:flex;align-items:center;gap:15px;')}>
                {v.donutEl}
                <div style={s('flex:1;display:flex;flex-direction:column;gap:7px;font-size:10px;')}>
                  {v.donutLegend.map((d, i) => (<div key={i} onClick={d.on} style={s('display:flex;align-items:center;gap:7px;cursor:pointer;')}><span style={{ ...s('width:8px;height:8px;border-radius:2px;'), background: d.color }}></span><span style={s('flex:1;color:#9aa7c2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;')}>{d.name}</span><span style={s("font-family:'IBM Plex Mono';color:#cdd6e8;")}>{d.pct}</span></div>))}
                </div>
              </div>
            </div>
            <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:13px;flex:1;')}>
              <div style={s("font:600 9.5px 'IBM Plex Sans';letter-spacing:.09em;text-transform:uppercase;color:#7e8aa6;margin-bottom:11px;")}>{v.contribTitle}</div>
              <div style={s('display:flex;flex-direction:column;gap:9px;')}>
                {v.contribRows.map((c, i) => (<div key={i} style={s('display:flex;align-items:center;gap:9px;')}><span style={s("width:48px;font-family:'IBM Plex Mono';font-size:11px;color:#cdd6e8;")}>{c.t}</span><div style={s('flex:1;height:7px;background:#13203a;border-radius:4px;overflow:hidden;display:flex;')}><div style={{ ...s('height:100%;'), width: c.w, background: c.color, marginLeft: c.alignRight ? 'auto' : undefined }}></div></div><span style={{ ...s("width:42px;text-align:right;font-family:'IBM Plex Mono';font-size:10px;"), color: c.color }}>{c.v}</span></div>))}
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  _renderStocks(v) {
    return (
      <div style={s('padding:16px;display:flex;flex-direction:column;gap:13px;')}>
        <div style={s('display:flex;align-items:center;justify-content:space-between;')}>
          <div><div style={s("font:600 17px 'IBM Plex Sans';color:#e8edf7;")}>{v.stocksTitle}</div><div style={s("font-family:'IBM Plex Mono';font-size:10.5px;color:#6b7794;margin-top:3px;")}>{v.stocksCount}</div></div>
          <div style={s('display:flex;align-items:center;gap:8px;background:#0e1422;border:1px solid #1d2840;border-radius:8px;padding:8px 12px;width:280px;')}>
            <svg width="13" height="13" viewBox="0 0 16 16" style={{ fill: 'none', stroke: '#5d6a85', strokeWidth: 1.6 }}><circle cx="7" cy="7" r="4.5"></circle><line x1="11" y1="11" x2="14.5" y2="14.5" style={{ strokeLinecap: 'round' }}></line></svg>
            <input value={v.query} onChange={(e) => this.setState({ query: e.target.value })} placeholder="Filter by ticker, name, sector…" style={s("flex:1;background:transparent;border:none;outline:none;color:#e8edf7;font:400 11.5px 'IBM Plex Sans';")} />
          </div>
        </div>
        <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;overflow:hidden;')}>
          <div style={s("display:grid;grid-template-columns:74px 1fr 150px 64px 70px 86px 92px 72px 72px 60px;gap:8px;padding:9px 14px;border-bottom:1px solid #1d2840;font:600 8.5px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;color:#6b7794;")}>
            {v.stocksHead.map((h, i) => (<span key={i} onClick={h.on} style={{ ...s('cursor:pointer;'), textAlign: h.align, color: h.color }}>{h.label}{h.caret}</span>))}
          </div>
          {v.stocksRows.map((r) => (
            <div key={r.rk} onClick={r.open} className="dc-row" style={s('display:grid;grid-template-columns:74px 1fr 150px 64px 70px 86px 92px 72px 72px 60px;gap:8px;align-items:center;padding:7.5px 14px;border-bottom:1px solid #131c2f;font-size:11px;cursor:pointer;')}>
              <span style={s("font-family:'IBM Plex Mono';font-weight:600;color:#e8edf7;")}>{r.t}</span>
              <span style={s('color:#9aa7c2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;')}>{r.n}</span>
              <span style={s('color:#6b7794;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;')}>{r.s}</span>
              <span style={{ ...s("text-align:right;font:500 9px 'IBM Plex Mono';"), color: r.fundColor }}>{r.fundTag}</span>
              <span style={s("font-family:'IBM Plex Mono';text-align:right;color:#cdd6e8;")}>{r.wStr}</span>
              <span style={s("font-family:'IBM Plex Mono';text-align:right;color:#e8edf7;")}>{r.mvStr}</span>
              <span style={s("font-family:'IBM Plex Mono';text-align:right;color:#cdd6e8;")}>{r.pxStr}</span>
              <span style={{ ...s("font-family:'IBM Plex Mono';text-align:right;"), color: r.dayColor }}>{r.dayStr}</span>
              <span style={{ ...s("font-family:'IBM Plex Mono';text-align:right;"), color: r.mtdColor }}>{r.mtdStr}</span>
              <span style={s("font-family:'IBM Plex Mono';text-align:right;color:#7e8aa6;")}>{r.peStr}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  _renderSectors(v) {
    return (
      <div style={s('height:calc(100vh - 48px);padding:16px;display:flex;flex-direction:column;gap:13px;')}>
        <div style={s('flex:0 0 auto;')}><div style={s("font:600 17px 'IBM Plex Sans';color:#e8edf7;")}>Sectors</div><div style={s("font-family:'IBM Plex Mono';font-size:10.5px;color:#6b7794;margin-top:3px;")}>The five UOIG groups across the combined endowment · click a column to drill in, a card to open the holding</div></div>
        <div style={s('flex:1;min-height:0;display:grid;grid-template-columns:repeat(5,1fr);gap:12px;')}>
          {v.sectorCols.map((c) => (
            <div key={c.name} style={s('display:flex;flex-direction:column;min-height:0;background:#0b0f1a;border:1px solid #1d2840;border-radius:10px;overflow:hidden;')}>
              <div style={{ ...s('height:3px;flex:0 0 auto;'), background: c.color }}></div>
              <div onClick={c.on} className="dc-hover" style={s('flex:0 0 auto;padding:12px 13px;border-bottom:1px solid #1d2840;cursor:pointer;')}>
                <div style={s('display:flex;justify-content:space-between;align-items:center;')}>
                  <div style={s('display:flex;align-items:center;gap:8px;min-width:0;')}><span style={{ ...s('width:9px;height:9px;border-radius:3px;flex:0 0 auto;'), background: c.color }}></span><span style={s("font:600 13.5px 'IBM Plex Sans';color:#e8edf7;")}>{c.name}</span></div>
                  <span style={s("font-family:'IBM Plex Mono';font-size:15px;color:#e8edf7;")}>{c.shareStr}</span>
                </div>
                <div style={s("font-family:'IBM Plex Mono';font-size:8.5px;color:#5d6a85;margin-top:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")}>{c.members}</div>
                <div style={s('display:flex;justify-content:space-between;align-items:center;margin-top:9px;')}><span style={s("font-family:'IBM Plex Mono';font-size:9.5px;color:#6b7794;")}>{c.count} holding{c.count === 1 ? '' : 's'}</span><span style={{ ...s("font-family:'IBM Plex Mono';font-size:10.5px;"), color: c.retColor }}>MTD {c.retStr}</span></div>
                {!c.singleFund && <div style={s('margin-top:9px;height:5px;border-radius:3px;background:#13203a;overflow:hidden;display:flex;')}><div style={{ ...s('background:#5a93f9;height:100%;'), width: c.gPct }}></div><div style={{ ...s('background:#f4a531;height:100%;'), width: c.vPct }}></div></div>}
              </div>
              <div style={s('flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;padding:9px;display:flex;flex-direction:column;gap:8px;')}>
                {c.cards.length === 0
                  ? <div style={s("font-family:'IBM Plex Mono';font-size:10px;color:#3c465e;text-align:center;padding:16px 0;")}>No holdings</div>
                  : c.cards.map((r) => (
                    <div key={r.rk} onClick={r.open} className="dc-row" style={s('background:#0e1422;border:1px solid #1d2840;border-radius:8px;padding:9px 10px;cursor:pointer;')}>
                      <div style={s('display:flex;justify-content:space-between;align-items:center;gap:6px;')}>
                        <span style={s("font-family:'IBM Plex Mono';font-weight:600;font-size:12.5px;color:#e8edf7;")}>{r.t}</span>
                        <span style={{ ...s("font:500 8.5px 'IBM Plex Mono';letter-spacing:.04em;"), color: r.fundColor }}>{r.fundTag}</span>
                      </div>
                      <div style={s("font:400 10.5px 'IBM Plex Sans';color:#9aa7c2;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")}>{r.n}</div>
                      <div style={s('display:flex;justify-content:space-between;align-items:center;margin-top:8px;')}>
                        <span style={s("font-family:'IBM Plex Mono';font-size:9.5px;color:#6b7794;")}>Wt {r.wStr}</span>
                        <span style={s('display:flex;gap:9px;')}><span style={{ ...s("font-family:'IBM Plex Mono';font-size:9.5px;"), color: r.dayColor }}>{r.dayStr}</span><span style={{ ...s("font-family:'IBM Plex Mono';font-size:9.5px;"), color: r.mtdColor }}>MTD {r.mtdStr}</span></span>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  _yc(str) { return /^\+/.test(str) ? '#21d07a' : (/^-/.test(str) ? '#ff5666' : '#9aa7c2') }

  // dispatch the active stock-detail tab through the live yfinance payload,
  // handling the loading / fetch-error / no-coverage states uniformly.
  _stkTabBody(v) {
    const tab = v.stkTab
    if (tab === 'thesis') {
      const t = v.thesisDetail
      if (t === 'loading' || t === undefined) return this._stkStub('Thesis', 'loading…', 'Loading the latest thesis.')
      if (t === 'error') return this._stkStub('Thesis', 'load failed', 'Could not load the thesis. Reopen the tab to retry.')
      return (t.thesis && t.thesis.points && t.thesis.points.length) ? this._renderThesis(t.thesis) : this._stkStub('Thesis', 'THESIS.md', 'No thesis recorded for this holding yet. Add three points under its ticker in THESIS.md.')
    }
    if (tab === 'predictions') {
      const p = v.predDetail
      if (p === 'loading' || p === undefined) return this._stkStub('Predictions', 'fetching Kalshi…', 'Pulling live prediction markets from Kalshi — one moment.')
      if (p === 'error') return this._stkStub('Predictions', 'fetch failed', 'Could not reach Kalshi. Reopen the tab to retry.')
      return (p.cards && p.cards.length) ? this._renderPredictions(p.cards) : this._stkStub('Predictions', 'Kalshi', 'No prediction markets are mapped for this holding yet. Add up to five in PREDICTION_MARKETS.md.')
    }
    const d = v.stkDetail
    if (d === 'loading' || d === undefined) return this._stkStub(v.stkTab, 'fetching live data…', 'Pulling the latest from yfinance — one moment.')
    if (d === 'error') return this._stkStub(v.stkTab, 'fetch failed', 'Could not reach the research feed. The backend may be offline or Yahoo rate-limited the request — reopen the stock to retry.')
    if (tab === 'financials') return d.financials ? this._renderFinancials(d.financials) : this._stkStub('Financials', 'quarterly_income_stmt', 'No quarterly financials are available for this security from yfinance.')
    if (tab === 'earnings') return d.earnings ? this._renderEarnings(d.earnings) : this._stkStub('Most Recent Earnings', 'get_earnings_dates', 'No earnings history is available for this security from yfinance.')
    if (tab === 'news') return (d.news && d.news.length) ? this._renderNews(d.news) : this._stkStub('Recent News', 'ticker.news', 'No recent news is available for this security from yfinance.')
    if (tab === 'research') return d.research ? this._renderResearch(d.research) : this._stkStub('Analyst Research', 'upgrades_downgrades', 'No analyst coverage is available for this security from yfinance.')
    return null
  }

  _card(title, source, children, pad) {
    return (
      <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:' + (pad || 16) + 'px;')}>
        <div style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.1em;text-transform:uppercase;color:#7e8aa6;margin-bottom:13px;")}>{title}{source ? <span style={s("font-family:'IBM Plex Mono';font-weight:400;color:#3c465e;text-transform:none;letter-spacing:0;")}> · {source}</span> : null}</div>
        {children}
      </div>
    )
  }

  _renderFinancials(fin) {
    const maxRev = Math.max.apply(null, fin.bars.map((b) => b.revenue || 0).concat([1]))
    const top = this._card('Financials', 'quarterly_income_stmt', (
      <div style={s('display:grid;grid-template-columns:minmax(0,1fr) 430px;gap:22px;')}>
        <div>
          <div style={s("display:flex;gap:15px;font:500 10px 'IBM Plex Sans';margin-bottom:12px;")}><span style={s('color:#5a93f9;')}>■ Revenue</span><span style={s('color:#21d07a;')}>■ Net income</span></div>
          <div style={s('display:flex;align-items:flex-end;gap:16px;height:140px;padding:0 4px;')}>
            {fin.bars.map((b, i) => {
              const revH = Math.max(2, (b.revenue || 0) / maxRev * 100)
              const niH = b.revenue ? Math.max(0, Math.min(100, (b.netIncome || 0) / b.revenue * 100)) : 0
              const last = i === fin.bars.length - 1
              return (
                <div key={i} style={s('flex:1;display:flex;flex-direction:column;align-items:center;gap:8px;height:100%;justify-content:flex-end;')}>
                  <div style={{ ...s('position:relative;width:60%;border-radius:3px 3px 0 0;'), height: revH + '%', background: last ? '#7fb0ff' : '#5a93f9' }}><div style={{ ...s('position:absolute;left:0;right:0;bottom:0;background:#21d07a;border-radius:0 0 3px 3px;'), height: niH + '%' }}></div></div>
                  <span style={{ ...s("font-family:'IBM Plex Mono';font-size:9px;"), color: last ? '#cdd6e8' : '#6b7794' }}>{b.period}</span>
                </div>
              )
            })}
          </div>
          {fin.caption ? <div style={s("font:500 11px 'IBM Plex Sans';color:#9aa7c2;margin-top:12px;")}>{fin.caption}</div> : null}
        </div>
        <div>
          <div style={s("display:grid;grid-template-columns:1fr 72px 72px 60px;gap:6px;padding-bottom:8px;border-bottom:1px solid #1d2840;font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;")}><span></span><span style={s('text-align:right;')}>Latest</span><span style={s('text-align:right;')}>Prior</span><span style={s('text-align:right;')}>YoY</span></div>
          {fin.rows.map((r, i) => (
            <div key={i} style={s('display:grid;grid-template-columns:1fr 72px 72px 60px;gap:6px;padding:8px 0;border-bottom:1px solid #131c2f;font-size:11px;')}><span style={s('color:#9aa7c2;')}>{r.label}</span><span style={s("font-family:'IBM Plex Mono';text-align:right;color:#e8edf7;")}>{r.cur}</span><span style={s("font-family:'IBM Plex Mono';text-align:right;color:#9aa7c2;")}>{r.prev}</span><span style={{ ...s("font-family:'IBM Plex Mono';text-align:right;"), color: this._yc(r.yoy) }}>{r.yoy}</span></div>
          ))}
        </div>
      </div>
    ))
    return (
      <div style={s('display:flex;flex-direction:column;gap:14px;')}>
        {top}
        {fin.statement && fin.statement.rows && fin.statement.rows.length ? this._statementGrid(fin.statement) : null}
      </div>
    )
  }

  // Last-4-quarters income statement (line items x quarters), Option A grid.
  _statementGrid(st) {
    const cols = '1.7fr repeat(4,minmax(0,1fr))'
    const fmt = (v, eps) => v == null ? '—' : (eps ? '$' + v.toFixed(2) : this._kd(v))
    const labelColor = (k) => k === 'exp' ? '#8290ad' : ((k === 'top' || k === 'sub' || k === 'net') ? '#cdd6e8' : '#9aa7c2')
    const valColor = (k) => k === 'exp' ? '#8290ad' : ((k === 'top' || k === 'net') ? '#e8edf7' : '#cdd6e8')
    const rev = (st.rows.find((r) => r.label === 'Revenue') || {}).vals
    const net = (st.rows.find((r) => r.label === 'Net income') || {}).vals
    let foot = null
    if (rev && net && rev[0] && rev[3] && net[0] != null && net[3] != null) {
      foot = 'Net margin ' + (net[0] / rev[0] * 100).toFixed(1) + '% → ' + (net[3] / rev[3] * 100).toFixed(1) + '%'
    }
    return this._card('Quarterly income statement', 'quarterly_income_stmt', (
      <div>
        <div style={{ ...s('display:grid;gap:6px;padding-bottom:7px;border-bottom:1px solid #1d2840;'), gridTemplateColumns: cols }}>
          <span style={s("font-family:'IBM Plex Mono';font-size:8.5px;color:#6b7794;")}>USD · quarterly</span>
          {st.quarters.map((q, i) => (<span key={i} style={s("font-family:'IBM Plex Mono';font-size:9.5px;text-align:right;color:#9aa7c2;")}>{q}</span>))}
        </div>
        {st.rows.map((r, i) => {
          const sub = r.kind === 'sub' || r.kind === 'net' || r.kind === 'eps'
          return (
            <div key={i} style={{ ...s('display:grid;gap:6px;padding:7px 0;align-items:center;'), gridTemplateColumns: cols, borderTop: sub ? '1px solid #1a2336' : 'none' }}>
              <span style={{ ...s('font-size:11px;'), color: labelColor(r.kind), fontWeight: (sub || r.kind === 'top') ? 500 : 400 }}>{r.label}</span>
              {r.vals.map((v, j) => (<span key={j} style={{ ...s("font-family:'IBM Plex Mono';font-size:11px;text-align:right;"), color: valColor(r.kind), fontWeight: (j === 3 && (r.kind === 'top' || r.kind === 'net')) ? 500 : 400 }}>{fmt(v, r.kind === 'eps')}</span>))}
            </div>
          )
        })}
        {foot ? <div style={s("font:500 10.5px 'IBM Plex Sans';color:#6b7794;margin-top:10px;")}>{foot}</div> : null}
      </div>
    ))
  }

  _renderEarnings(e) {
    const beatPos = (e.beat || 0) >= 0
    return (
      <div style={s('display:flex;flex-direction:column;gap:14px;')}>
        <div style={s('background:linear-gradient(180deg,#0c1f18,#0e1422);border:1px solid #1d4536;border-radius:9px;padding:16px;')}>
          <div style={s('display:flex;align-items:center;gap:10px;margin-bottom:13px;flex-wrap:wrap;')}><span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.1em;text-transform:uppercase;color:#7e8aa6;")}>Most Recent Earnings</span><span style={s("font-family:'IBM Plex Mono';font-size:10px;color:#6b7794;")}>{e.qtrLabel} · {e.when}</span>{e.beat != null ? <span style={{ ...s("margin-left:auto;font:600 10px 'IBM Plex Sans';border-radius:5px;padding:4px 10px;"), color: beatPos ? '#21d07a' : '#ff5666', background: beatPos ? '#0c2a1e' : '#2a1115', border: '1px solid ' + (beatPos ? '#1d4536' : '#4a1f25') }}>EPS {beatPos ? 'beat' : 'miss'} {this._sign(e.beat, 1)}%</span> : null}</div>
          <div style={s('display:grid;grid-template-columns:repeat(4,1fr);gap:13px;')}>
            {[['EPS actual / est', e.epsActual, e.epsEst], ['Revenue actual / est', e.revActual, e.revEst], ['Revenue YoY', e.revYoY, null], ['Next report est', e.next, null]].map((c, i) => (
              <div key={i} style={s('background:#0a1410;border:1px solid #163a2c;border-radius:7px;padding:12px;')}><div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;")}>{c[0]}</div><div style={{ ...s("font-family:'IBM Plex Mono';font-size:16px;margin-top:6px;"), color: i === 2 ? this._yc(c[1]) : '#e8edf7' }}>{c[1]}{c[2] ? <span style={s('color:#5d6a85;font-size:12px;')}> / {c[2]}</span> : null}</div></div>
            ))}
          </div>
        </div>
        {e.history && e.history.length ? this._card('EPS History', 'estimate vs reported', (
          <div>
            <div style={s("display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;padding:8px 0;border-bottom:1px solid #1d2840;font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;")}><span>Quarter</span><span style={s('text-align:right;')}>Estimate</span><span style={s('text-align:right;')}>Actual</span><span style={s('text-align:right;')}>Surprise</span></div>
            {e.history.map((h, i) => (
              <div key={i} style={s('display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;padding:9px 0;border-bottom:1px solid #131c2f;font-size:11px;')}><span style={s("font-family:'IBM Plex Mono';color:#cdd6e8;")}>{h.q}</span><span style={s("font-family:'IBM Plex Mono';text-align:right;color:#9aa7c2;")}>{h.est}</span><span style={s("font-family:'IBM Plex Mono';text-align:right;color:#e8edf7;")}>{h.act}</span><span style={{ ...s("font-family:'IBM Plex Mono';text-align:right;"), color: this._yc(h.surprise) }}>{h.surprise}</span></div>
            ))}
          </div>
        ), 16) : null}
      </div>
    )
  }

  _renderNews(news) {
    return this._card('Recent News', 'ticker.news', (
      <NewsList auth={this.state.auth} news={news} ticker={this.state.ticker} />
    ))
  }

  _renderResearch(r) {
    const c = r.consensus
    const lblColor = c && /Buy/.test(c.label) ? '#21d07a' : (c && /Sell/.test(c.label) ? '#ff5666' : '#cdd6e8')
    let bar = null, range = null
    if (c) {
      const tot = (c.strongBuy + c.buy + c.hold + c.sell) || 1
      const w = (n) => (n / tot * 100).toFixed(1) + '%'
      bar = { sb: w(c.strongBuy), b: w(c.buy), h: w(c.hold), s: w(c.sell) }
      if (c.low != null && c.high != null && c.high > c.low) {
        const pos = (x) => Math.max(0, Math.min(100, (x - c.low) / (c.high - c.low) * 100)).toFixed(1) + '%'
        const upside = (c.mean != null && c.current) ? (c.mean - c.current) / c.current * 100 : null
        range = { meanPos: pos(c.mean), curPos: pos(c.current), upside: upside != null ? this._sign(upside, 1) + '%' : '—', upColor: this._col(upside) }
      }
    }
    return (
      <div style={s('display:flex;flex-direction:column;gap:14px;')}>
        {c ? (
          <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:16px;')}>
            <div style={s('display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;')}><span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.1em;text-transform:uppercase;color:#7e8aa6;")}>Analyst Consensus</span><span style={s("font-family:'IBM Plex Mono';font-size:10px;color:#6b7794;")}>{c.total} analysts</span></div>
            <div style={s('display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:26px;')}>
              <div>
                <div style={s('display:flex;align-items:center;gap:12px;margin-bottom:14px;')}><div style={{ ...s("font:700 22px 'IBM Plex Sans';"), color: lblColor }}>{c.label}</div><div style={s('flex:1;height:1px;background:#1d2840;')}></div></div>
                <div style={s('display:flex;height:11px;border-radius:6px;overflow:hidden;')}><div style={{ ...s('background:#21d07a;'), width: bar.sb }}></div><div style={{ ...s('background:#7fcf8a;'), width: bar.b }}></div><div style={{ ...s('background:#6b7794;'), width: bar.h }}></div><div style={{ ...s('background:#ff5666;'), width: bar.s }}></div></div>
                <div style={s('display:grid;grid-template-columns:1fr 1fr;gap:7px 16px;margin-top:12px;font-size:10.5px;')}>
                  {[['Strong Buy', '#21d07a', c.strongBuy], ['Buy', '#7fcf8a', c.buy], ['Hold', '#6b7794', c.hold], ['Sell', '#ff5666', c.sell]].map((x, i) => (
                    <div key={i} style={s('display:flex;align-items:center;gap:6px;')}><span style={{ ...s('width:8px;height:8px;border-radius:2px;'), background: x[1] }}></span><span style={s('flex:1;color:#9aa7c2;')}>{x[0]}</span><span style={s("font-family:'IBM Plex Mono';color:#cdd6e8;")}>{x[2]}</span></div>
                  ))}
                </div>
              </div>
              <div style={s('display:flex;flex-direction:column;justify-content:center;height:100%;')}>
                {range ? (
                  <div>
                    <div style={s("display:flex;justify-content:space-between;font-family:'IBM Plex Mono';font-size:9.5px;color:#6b7794;")}><span>Low ${c.low.toFixed(0)}</span><span style={{ color: lblColor }}>Mean ${c.mean.toFixed(0)}</span><span>High ${c.high.toFixed(0)}</span></div>
                    <div style={s('position:relative;height:8px;border-radius:5px;background:#13203a;margin-top:8px;')}><div style={{ ...s('position:absolute;left:0;height:100%;border-radius:5px;background:linear-gradient(90deg,#1d2840,#21d07a);'), width: range.meanPos }}></div><div style={{ ...s('position:absolute;top:-4px;width:3px;height:16px;border-radius:2px;background:#21d07a;'), left: range.meanPos }}></div><div style={{ ...s('position:absolute;top:-4px;width:2px;height:16px;background:#e8edf7;'), left: range.curPos }}></div></div>
                    <div style={s('position:relative;height:13px;margin-top:5px;')}><span style={{ ...s("position:absolute;transform:translateX(-50%);font-family:'IBM Plex Mono';font-size:9px;color:#cdd6e8;"), left: range.curPos }}>${c.current.toFixed(0)} now</span></div>
                    <div style={{ ...s("font:500 11px 'IBM Plex Sans';margin-top:13px;"), color: range.upColor }}>Mean target ${c.mean.toFixed(0)} · implies {range.upside} upside</div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}
        {r.estimates && r.estimates.length ? this._card('Forward Estimates', 'earnings_estimate', (
          <div>
            <div style={s("display:grid;grid-template-columns:1.4fr 1fr 64px 1fr 70px;gap:6px;padding:8px 0;border-bottom:1px solid #1d2840;font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;")}><span>Period</span><span style={s('text-align:right;')}>EPS est</span><span style={s('text-align:right;')}># An.</span><span style={s('text-align:right;')}>Rev est</span><span style={s('text-align:right;')}>Rev YoY</span></div>
            {r.estimates.map((e, i) => (
              <div key={i} style={s('display:grid;grid-template-columns:1.4fr 1fr 64px 1fr 70px;gap:6px;padding:9px 0;border-bottom:1px solid #131c2f;font-size:11px;')}><span style={s('color:#9aa7c2;')}>{e.period}</span><span style={s("font-family:'IBM Plex Mono';text-align:right;color:#e8edf7;")}>{e.eps}</span><span style={s("font-family:'IBM Plex Mono';text-align:right;color:#6b7794;")}>{e.epsN}</span><span style={s("font-family:'IBM Plex Mono';text-align:right;color:#cdd6e8;")}>{e.rev}</span><span style={{ ...s("font-family:'IBM Plex Mono';text-align:right;"), color: this._yc(e.revYoY) }}>{e.revYoY}</span></div>
            ))}
          </div>
        ), 16) : null}
        {r.actions && r.actions.length ? this._card('Recent Research', 'upgrades_downgrades', (
          <div style={s('display:flex;flex-direction:column;')}>
            {r.actions.map((a, i) => {
              const col = a.action === 'Upgrade' ? ['#21d07a', '#0c2a1e', '#1d4536'] : a.action === 'Downgrade' ? ['#ff5666', '#2a1115', '#4a1f25'] : a.action === 'Initiate' ? ['#5a93f9', '#0e1c33', '#1d3a5c'] : ['#9aa7c2', '#13203a', '#13203a']
              return (
                <div key={i} style={s('display:flex;align-items:center;gap:10px;padding:11px 0;border-bottom:1px solid #131c2f;')}><span style={{ ...s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.04em;text-transform:uppercase;border-radius:4px;padding:4px 7px;flex:0 0 auto;width:74px;text-align:center;"), color: col[0], background: col[1], border: '1px solid ' + col[2] }}>{a.action}</span><div style={s('flex:1;')}><div style={s("font:600 12px 'IBM Plex Sans';color:#cdd6e8;")}>{a.firm}</div><div style={s("font-family:'IBM Plex Mono';font-size:10px;color:#6b7794;")}>{a.grade}</div></div><div style={s('text-align:right;')}><div style={s("font-family:'IBM Plex Mono';font-size:11px;color:#e8edf7;")}>{a.target}</div><div style={s("font-family:'IBM Plex Mono';font-size:9px;color:#6b7794;")}>{a.date}</div></div></div>
              )
            })}
          </div>
        ), 16) : null}
      </div>
    )
  }

  _renderThesis(t) {
    return (
      <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:16px;')}>
        <div style={s('display:flex;align-items:center;justify-content:space-between;margin-bottom:15px;')}>
          <span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.1em;text-transform:uppercase;color:#7e8aa6;")}>Investment Thesis</span>
          <span style={s("font-family:'IBM Plex Mono';font-size:10px;color:#6b7794;")}>Most recent · {t.date}{t.analyst ? ' · ' + t.analyst : ''}</span>
        </div>
        <div style={s('display:flex;flex-direction:column;gap:11px;')}>
          {t.points.map((p, i) => (
            <div key={i} style={s('display:flex;gap:13px;align-items:flex-start;background:#0a0f1a;border:1px solid #1d2840;border-radius:8px;padding:14px 15px;')}>
              <span style={s("width:24px;height:24px;flex:0 0 auto;border-radius:7px;background:#13203a;color:#5a93f9;display:flex;align-items:center;justify-content:center;font:600 12px 'IBM Plex Mono';")}>{i + 1}</span>
              <span style={s("font:400 13px/1.6 'IBM Plex Sans';color:#cdd6e8;")}>{p}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  _renderPredictions(cards) {
    const catColor = (c) => ({ 'Politics': '#c06fd6', 'Economics': '#f4a531', 'Financials': '#5a93f9', 'Science and Technology': '#21d07a', 'Commodities': '#e8674c' }[c] || '#3a4a6a')
    const outColor = (o, i) => (o.label === 'No' ? '#ff5666' : o.label === 'Yes' ? '#21d07a' : (i === 0 ? '#21d07a' : '#5a93f9'))
    return (
      <div style={s('display:grid;grid-template-columns:1fr 1fr;gap:13px;')}>
        {cards.map((c, ci) => (
          <a key={ci} href={c.url} target="_blank" rel="noreferrer" style={s('display:block;text-decoration:none;background:#0b0f1a;border:1px solid #1d2840;border-radius:12px;padding:17px 18px;')}>
            <div style={s('display:flex;align-items:center;gap:10px;')}>
              <div style={{ ...s("width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;font:700 13px 'IBM Plex Sans';color:#0b0f1a;flex:0 0 auto;"), background: catColor(c.category) }}>{(c.category || '?')[0]}</div>
              <span style={s("font:600 11px 'IBM Plex Sans';letter-spacing:.07em;text-transform:uppercase;color:#7e8aa6;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")}>{c.category}</span>
            </div>
            <div style={s("font:600 15px/1.3 'IBM Plex Sans';color:#e8edf7;margin-top:12px;")}>{c.title}</div>
            <div style={s("font-family:'IBM Plex Mono';font-size:11px;color:#5d6a85;margin-top:5px;")}>{c.closeStr}</div>
            <div style={s('display:flex;flex-direction:column;gap:13px;margin-top:15px;')}>
              {c.outcomes.map((o, i) => (
                <div key={i} style={s('display:flex;align-items:center;gap:12px;')}>
                  <div style={s('flex:1;min-width:0;')}>
                    <div style={s("font:400 14px 'IBM Plex Sans';color:#e8edf7;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")}>{o.label}</div>
                    <div style={s('height:2px;border-radius:2px;background:#1a2338;margin-top:7px;overflow:hidden;')}><div style={{ ...s('height:100%;border-radius:2px;'), width: Math.max(4, Math.min(100, o.pct)) + '%', background: outColor(o, i) }}></div></div>
                  </div>
                  {o.mult ? <span style={s("font-family:'IBM Plex Mono';font-size:13px;color:#6b7794;flex:0 0 auto;")}>{o.mult}</span> : null}
                  <span style={s("font:700 14px 'IBM Plex Sans';color:#e8edf7;border:1px solid #265c44;border-radius:999px;padding:6px 13px;flex:0 0 auto;min-width:52px;text-align:center;")}>{o.pct}%</span>
                </div>
              ))}
            </div>
            <div style={s("display:flex;justify-content:space-between;align-items:center;margin-top:16px;font-family:'IBM Plex Mono';font-size:11px;color:#5d6a85;")}>
              <span>${c.volume.toLocaleString('en-US')} vol</span>
              <span>{c.marketCount} market{c.marketCount === 1 ? '' : 's'}</span>
            </div>
          </a>
        ))}
      </div>
    )
  }

  _stkStub(title, source, body) {
    return (
      <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:16px;')}>
        <div style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.1em;text-transform:uppercase;color:#7e8aa6;margin-bottom:14px;")}>{title} <span style={s("font-family:'IBM Plex Mono';font-weight:400;color:#3c465e;text-transform:none;letter-spacing:0;")}>· {source}</span></div>
        <div style={s('display:flex;flex-direction:column;align-items:center;text-align:center;gap:8px;padding:26px 12px;color:#5d6a85;')}>
          <span style={s('font-size:22px;color:#3c4a66;')}>⊟</span>
          <div style={s("font:600 12.5px 'IBM Plex Sans';color:#8290ad;")}>Not yet wired to the API</div>
          <div style={s("font:400 11px/1.55 'IBM Plex Sans';max-width:380px;")}>{body}</div>
        </div>
      </div>
    )
  }

  _renderStockMsg(v) {
    const err = v.stkErr
    return (
      <div style={s('padding:18px;display:flex;flex-direction:column;gap:15px;')}>
        <div onClick={() => this._go(this.state.prevView || 'dashboard')} style={s("display:inline-flex;align-items:center;gap:6px;font:500 11px 'IBM Plex Sans';color:#6b7794;cursor:pointer;width:fit-content;")}>‹ {v.stkBackLabel || 'Back'}</div>
        <div style={s('display:flex;flex-direction:column;align-items:center;text-align:center;gap:10px;padding:80px 12px;color:#5d6a85;')}>
          <span style={s('font-size:26px;color:#3c4a66;')}>{err ? '⚠' : '✦'}</span>
          <div style={s("font:600 13px 'IBM Plex Sans';color:#8290ad;")}>{err ? 'No equity found' : 'Loading ' + (this.state.ticker || '') + '…'}</div>
          <div style={s("font:400 11px/1.55 'IBM Plex Sans';max-width:360px;")}>{err ? 'Yahoo Finance has no equity matching “' + (this.state.ticker || '') + '”. Check the symbol and try the search box again.' : 'Pulling live quote, price history and fundamentals from Yahoo Finance.'}</div>
        </div>
      </div>
    )
  }

  _renderStock(v) {
    const stk = v.stk
    return (
      <div style={s('padding:18px;display:flex;flex-direction:column;gap:15px;')}>
        <div onClick={() => this._go(this.state.prevView || 'dashboard')} style={s("display:inline-flex;align-items:center;gap:6px;font:500 11px 'IBM Plex Sans';color:#6b7794;cursor:pointer;width:fit-content;")}>‹ {v.stkBackLabel}</div>
        {/* header */}
        <div style={s('display:flex;justify-content:space-between;align-items:flex-start;')}>
          <div style={s('display:flex;align-items:center;gap:13px;')}>
            <div>
              <div style={s('display:flex;align-items:center;gap:9px;')}>
                <span style={s("font-family:'IBM Plex Mono';font-size:26px;font-weight:600;color:#e8edf7;letter-spacing:-.01em;")}>{stk.t}</span>
                <span style={{ ...s("font:600 9px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;border-radius:5px;padding:3px 8px;"), color: stk.fundColor, border: '1px solid ' + stk.fundColor }}>{stk.fundLabel}</span>
              </div>
              <div style={s("font:400 14px 'IBM Plex Sans';color:#9aa7c2;margin-top:5px;")}>{stk.n}</div>
              <div style={s('display:flex;gap:6px;margin-top:7px;')}>
                <span onClick={() => this._group(stk.s) && this._openSector(this._group(stk.s), 'stock')} style={s("font:500 10px 'IBM Plex Sans';color:#9aa7c2;background:#0e1422;border:1px solid #1d2840;border-radius:5px;padding:3px 9px;cursor:pointer;")}>{stk.s}</span>
              </div>
            </div>
          </div>
          <div style={s('text-align:right;')}>
            <div style={s("font-family:'IBM Plex Mono';font-size:28px;font-weight:500;color:#e8edf7;")}>{stk.pxStr}</div>
            <div style={{ ...s("font-family:'IBM Plex Mono';font-size:13px;margin-top:2px;"), color: stk.dayColor }}>{stk.dayArrow} {stk.dayStr} {stk.dayAbs} today</div>
            <div style={s("font-family:'IBM Plex Mono';font-size:10px;color:#5d6a85;margin-top:3px;")}>{stk.asof}</div>
          </div>
        </div>
        {/* snapshot */}
        <div style={s('display:grid;grid-template-columns:repeat(7,1fr);gap:11px;')}>
          {v.stkSnapshot.map((st2, i) => (<div key={i} title={st2.tooltip} style={s('background:#0e1422;border:1px solid #1d2840;border-radius:8px;padding:11px 13px;')}><div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;color:#6b7794;")}>{st2.l}</div><div style={{ ...s("font-family:'IBM Plex Mono';margin-top:6px;color:#cdd6e8;"), fontSize: st2.size }}>{st2.v}</div></div>))}
        </div>
        {/* price chart (full width) */}
        <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;')}>
          <div style={s('display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;')}>
            <span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;")}>Price</span>
            <div style={s('display:flex;align-items:center;gap:3px;background:#0a0f1a;border:1px solid #1d2840;border-radius:8px;padding:3px;')}>{v.periods.map((p) => (<span key={p.k} onClick={p.on} style={{ ...s("padding:4px 9px;border-radius:5px;cursor:pointer;font-size:10px;font-family:'IBM Plex Mono';"), fontWeight: p.weight, background: p.bg, color: p.color }}>{p.k}</span>))}</div>
          </div>
          <div style={s("display:flex;gap:15px;font:500 10px 'IBM Plex Sans';margin-bottom:6px;")}>{v.stkChartLegend.map((l, i) => (<span key={i} style={{ color: l.color }}>{l.mark} {l.label}</span>))}</div>
          <div style={s('height:230px;')}>{v.stkChartEl}</div>
          <div style={s('margin-top:12px;')}><div style={s("display:flex;justify-content:space-between;font-family:'IBM Plex Mono';font-size:10px;color:#6b7794;margin-bottom:5px;")}><span>52W Low {stk.loStr}</span><span>52W High {stk.hiStr}</span></div><div style={s('height:6px;border-radius:4px;background:linear-gradient(90deg,#1d2840,#2a3a5c);position:relative;')}><div style={{ ...s('position:absolute;top:-3px;width:3px;height:12px;border-radius:2px;background:#e8edf7;'), left: stk.rangePos }}></div></div></div>
        </div>
        {/* tabs */}
        <div style={s('display:flex;gap:3px;border-bottom:1px solid #1d2840;')}>
          {v.stkTabs.map((t) => (<span key={t.key} onClick={t.on} style={{ ...s("padding:9px 15px;font-size:11.5px;font-family:'IBM Plex Sans';cursor:pointer;margin-bottom:-1px;"), fontWeight: t.weight, color: t.color, borderBottom: t.border }}>{t.label}</span>))}
        </div>
        {/* OVERVIEW */}
        {v.stkTab === 'overview' && (
          <div style={s('display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:14px;')}>
            <div style={s('display:flex;flex-direction:column;gap:14px;min-width:0;')}>
              <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:16px;')}>
                <div style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.1em;text-transform:uppercase;color:#7e8aa6;margin-bottom:10px;")}>Business</div>
                <div style={s("font:400 12.5px/1.65 'IBM Plex Sans';color:#b8c2d8;")}>{stk.descr}</div>
              </div>
              <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:16px;')}>
                <div style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.1em;text-transform:uppercase;color:#7e8aa6;margin-bottom:12px;")}>Company Facts</div>
                <div style={s('display:grid;grid-template-columns:1fr 1fr 1fr;gap:13px;')}>
                  {v.stkFacts.map((fct, i) => (<div key={i}><div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;")}>{fct.l}</div><div style={{ ...s("font:500 12px 'IBM Plex Sans';margin-top:3px;"), color: fct.color }}>{fct.v}</div></div>))}
                </div>
              </div>
            </div>
            <div style={s('display:flex;flex-direction:column;gap:14px;')}>
              <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;')}>
                <div style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;margin-bottom:13px;")}>{v.stkPos ? 'Position in ' + stk.fundLabel : 'Portfolio Position'}</div>
                {!v.stkPos ? (
                  <div style={s('display:flex;flex-direction:column;gap:8px;')}>
                    <div style={s("display:inline-flex;align-items:center;gap:7px;width:fit-content;font:600 9px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;color:#9aa7c2;background:#13203a;border:1px solid #24345a;border-radius:5px;padding:4px 9px;")}><span style={s('width:6px;height:6px;border-radius:50%;background:#6b7794;')}></span>Not held</div>
                    <div style={s("font:400 11.5px/1.6 'IBM Plex Sans';color:#8290ad;")}>{stk.t} is not currently held in the Tall Firs or Alumni Fund. This is a live Yahoo Finance lookup for research.</div>
                  </div>
                ) : (
                <div style={s('display:flex;flex-direction:column;gap:12px;')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:baseline;')}><span style={s('font-size:11px;color:#9aa7c2;')}>Portfolio weight</span><span style={s("font-family:'IBM Plex Mono';font-size:16px;color:#e8edf7;")}>{v.stkPos.weightStr}</span></div>
                  <div style={s('display:flex;justify-content:space-between;align-items:baseline;')}><span style={s('font-size:11px;color:#9aa7c2;')}>Market value</span><span style={s("font-family:'IBM Plex Mono';font-size:16px;color:#e8edf7;")}>{v.stkPos.valueStr}</span></div>
                  <div style={s('display:flex;justify-content:space-between;align-items:baseline;')}><span style={s('font-size:11px;color:#9aa7c2;')}>Shares</span><span style={s("font-family:'IBM Plex Mono';font-size:14px;color:#cdd6e8;")}>{v.stkPos.sharesStr}</span></div>
                  <div style={s('display:flex;justify-content:space-between;align-items:baseline;')}><span style={s('font-size:11px;color:#9aa7c2;')}>Contribution MTD</span><span style={{ ...s("font-family:'IBM Plex Mono';font-size:14px;"), color: v.stkPos.contribColor }}>{v.stkPos.contribStr}</span></div>
                </div>
                )}
              </div>
              <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;')}>
                <div style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;margin-bottom:13px;")}>Top Institutional Holders</div>
                {v.stkHoldersState === 'loading' ? (
                  <div style={s("font:400 11px 'IBM Plex Sans';color:#5d6a85;")}>Loading 13F holders…</div>
                ) : (v.stkHoldersState === 'error' || !v.stkHolders.length) ? (
                  <div style={s("font:400 11px/1.6 'IBM Plex Sans';color:#8290ad;")}>No institutional holder data available from Yahoo Finance.</div>
                ) : (
                  <div style={s('display:flex;flex-direction:column;gap:10px;')}>
                    <div style={s("display:grid;grid-template-columns:1fr auto;gap:8px;font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;")}><span>Holder</span><span style={s('text-align:right;')}>% Out</span></div>
                    {v.stkHolders.map((hd, i) => (
                      <div key={i} style={s('display:grid;grid-template-columns:1fr auto;gap:8px;align-items:baseline;')}>
                        <div style={s('min-width:0;')}>
                          <div style={s("font:500 11.5px 'IBM Plex Sans';color:#cdd6e8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")}>{hd.holder}</div>
                          <div style={s("font-family:'IBM Plex Mono';font-size:9.5px;color:#6b7794;margin-top:2px;")}>{hd.sharesStr} sh · {hd.valueStr}</div>
                        </div>
                        <span style={s("font-family:'IBM Plex Mono';font-size:13px;color:#e8edf7;")}>{hd.pctStr}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
        {v.stkTab !== 'overview' && this._stkTabBody(v)}
      </div>
    )
  }

  _renderOptimize(v) {
    const st = this.state, F = this.funds
    const key = st.optimizeFund || this.fundKeys[0]
    const f = F[key]
    const d = st.optimizeDiag[key]
    const tab = st.optimizeTab || 'diagnostics'
    const loading = d === 'loading' || d === undefined
    const errored = d === 'error'
    const data = (!loading && !errored) ? d : null
    const tabs = [['diagnostics', 'Diagnostics'], ['whatif', 'What-if'], ['optimizer', 'Optimizer']]
    return (
      <div style={s('padding:16px;display:flex;flex-direction:column;gap:14px;')}>
        <div style={s('display:flex;justify-content:space-between;align-items:flex-start;')}>
          <div>
            <div style={s("font:600 9px 'IBM Plex Sans';letter-spacing:.14em;text-transform:uppercase;color:#6b7794;")}>Optimization</div>
            <div style={s("font:600 21px 'IBM Plex Sans';color:#e8edf7;margin-top:3px;")}>{tab === 'whatif' ? 'What-if' : tab === 'optimizer' ? 'Optimizer' : 'Diagnostics'}</div>
          </div>
          <div style={s('display:flex;align-items:center;gap:10px;')}>
            <div style={s('display:flex;background:#0a0f1a;border:1px solid #1d2840;border-radius:8px;padding:3px;')}>
              {this.fundKeys.map((k) => {
                const on = k === key
                return <span key={k} onClick={() => this.setState({ optimizeFund: k })} style={{ ...s("padding:5px 13px;border-radius:5px;cursor:pointer;font:600 11px 'IBM Plex Sans';"), background: on ? '#13203a' : 'transparent', color: on ? F[k].color : '#6b7794', border: on ? '1px solid #28406e' : '1px solid transparent' }}>{F[k].name}</span>
              })}
            </div>
            <div style={s('text-align:right;')}>
              <div style={s("font-family:'IBM Plex Mono';font-size:11px;color:#9aa7c2;")}>vs {data ? data.benchmark : (f.benchShort || '—')}</div>
              <div style={s("font-family:'IBM Plex Mono';font-size:9px;color:#5d6a85;margin-top:2px;")}>{data ? (data.overlay + '% benchmark overlay') : 'Sample cov · 3Y daily'}</div>
            </div>
          </div>
        </div>
        <div style={s('display:flex;gap:3px;border-bottom:1px solid #1d2840;')}>
          {tabs.map(([k, label]) => (
            <span key={k} onClick={() => this.setState({ optimizeTab: k })} style={{ ...s("padding:9px 15px;font-size:11.5px;font-family:'IBM Plex Sans';cursor:pointer;margin-bottom:-1px;"), fontWeight: k === tab ? 600 : 500, color: k === tab ? '#e8edf7' : '#6b7794', borderBottom: k === tab ? '2px solid #5a93f9' : '2px solid transparent' }}>{label}</span>
          ))}
        </div>
        {tab === 'diagnostics' && loading && this._optimizeMsg('Computing active-risk diagnostics…')}
        {tab === 'diagnostics' && errored && this._optimizeMsg('Could not load diagnostics for ' + f.name + '.')}
        {tab === 'diagnostics' && data && this._renderOptimizeDiag(data)}
        {tab === 'whatif' && this._renderWhatifTab(key)}
        {tab === 'optimizer' && this._renderOptimizerTab(key)}
      </div>
    )
  }

  _optimizeMsg(text) {
    return <div style={s("background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:30px;display:flex;justify-content:center;color:#5d6a85;font:500 11px 'IBM Plex Sans';")}>{text}</div>
  }

  _renderOptimizeDiag(d) {
    const k = d.kpis, c = d.concentration
    const pct = (x, dp) => (x == null ? '—' : x.toFixed(dp == null ? 1 : dp) + '%')
    const kpis = [
      { l: 'Tracking Error', v: pct(k.tracking_error, 2), sub: 'active risk, ann.', accent: '#5a93f9', tooltip: 'Realized standard deviation of active returns.' },
      { l: 'Active Share', v: pct(k.active_share, 1), sub: 'vs benchmark', accent: '#5a93f9', tooltip: 'Percentage of the portfolio that differs from the benchmark.' },
      { l: 'Beta vs ' + d.benchmark, v: k.beta == null ? '—' : k.beta.toFixed(2), sub: '3Y daily', accent: '#2a3a5c', tooltip: 'Portfolio beta relative to the benchmark.' },
      { l: 'Portfolio Vol', v: pct(k.vol, 1), sub: 'total, ann.', accent: '#2a3a5c', tooltip: 'Total annualized volatility.' },
    ]
    const rows = (d.risk_contribution || []).slice(0, 12)
    const maxRC = Math.max.apply(null, rows.map((r) => Math.abs(r.risk_contrib)).concat([1]))
    const tilts = d.sector_tilts || []
    const maxTilt = Math.max.apply(null, tilts.map((t) => Math.abs(t.active)).concat([1]))
    return (
      <React.Fragment>
        <div style={s('display:grid;grid-template-columns:repeat(4,1fr);gap:11px;')}>
          {kpis.map((t, i) => (
            <div key={i} title={t.tooltip} style={{ ...s('background:#0e1422;border:1px solid #1d2840;border-radius:0 8px 8px 0;padding:11px 13px;'), borderLeft: '3px solid ' + t.accent }}>
              <div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")}>{t.l}</div>
              <div style={s("font-family:'IBM Plex Mono';font-size:20px;margin-top:5px;color:#e8edf7;")}>{t.v}</div>
              <div style={s('font-size:9px;color:#5d6a85;margin-top:2px;')}>{t.sub}</div>
            </div>
          ))}
        </div>
        <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;')}>
          <div style={s('display:flex;justify-content:space-between;align-items:center;margin-bottom:11px;')}>
            <span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;")}>Active Risk Contribution</span>
            <span style={s('font-size:9.5px;color:#5d6a85;')}>% of tracking error, by active bet</span>
          </div>
          <div style={s("display:grid;grid-template-columns:52px 1fr 62px 60px 56px 92px;gap:8px;font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;padding-bottom:7px;border-bottom:1px solid #1d2840;")}>
            <span>Ticker</span><span>Name</span><span style={s('text-align:right;')}>Port Wt</span><span style={s('text-align:right;')}>Bench</span><span style={s('text-align:right;')}>Active</span><span style={s('text-align:right;')}>Risk Contrib</span>
          </div>
          {rows.map((r, i) => {
            const col = r.active_w >= 0 ? '#21d07a' : '#ff5666'
            return (
              <div key={i} style={s('display:grid;grid-template-columns:52px 1fr 62px 60px 56px 92px;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid #131c2f;')}>
                <span style={s("font-family:'IBM Plex Mono';font-weight:500;font-size:12px;color:#e8edf7;")}>{r.t}</span>
                <span style={s("font:400 10.5px 'IBM Plex Sans';color:#8290ad;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")}>{r.name}</span>
                <span style={s("font-family:'IBM Plex Mono';font-size:11px;text-align:right;color:#cdd6e8;")}>{r.port_w.toFixed(1)}</span>
                <span style={s("font-family:'IBM Plex Mono';font-size:11px;text-align:right;color:#6b7794;")}>{r.bench_w.toFixed(2)}</span>
                <span style={{ ...s("font-family:'IBM Plex Mono';font-size:11px;text-align:right;"), color: col }}>{this._sign(r.active_w, 1)}</span>
                <span style={s('display:flex;align-items:center;gap:6px;justify-content:flex-end;')}>
                  <span style={{ ...s('height:6px;border-radius:3px;opacity:.8;'), width: Math.max(4, Math.abs(r.risk_contrib) / maxRC * 60) + 'px', background: col }}></span>
                  <span style={s("font-family:'IBM Plex Mono';font-size:11px;color:#cdd6e8;width:34px;text-align:right;")}>{Math.round(r.risk_contrib)}%</span>
                </span>
              </div>
            )
          })}
        </div>
        <div style={s('display:grid;grid-template-columns:1fr 1fr;gap:14px;')}>
          <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;')}>
            <div style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;margin-bottom:13px;")}>Active Sector Tilts</div>
            {tilts.map((t, i) => {
              const ow = t.active >= 0, col = ow ? '#21d07a' : '#ff5666', w = Math.abs(t.active) / maxTilt * 50
              return (
                <div key={i} style={s('display:grid;grid-template-columns:74px 1fr 44px;gap:8px;align-items:center;margin-bottom:9px;')}>
                  <span style={s("font:400 10.5px 'IBM Plex Sans';color:#9aa7c2;")}>{t.group}</span>
                  <div style={s('position:relative;height:14px;display:flex;align-items:center;')}>
                    <div style={s('position:absolute;left:50%;top:0;bottom:0;width:1px;background:#2a3a5c;')}></div>
                    <div style={{ ...s('position:absolute;left:50%;height:9px;border-radius:2px;opacity:.85;'), background: col, width: w + '%', transform: ow ? 'none' : 'translateX(-100%)' }}></div>
                  </div>
                  <span style={{ ...s("font-family:'IBM Plex Mono';font-size:11px;text-align:right;"), color: col }}>{this._sign(t.active, 1)}</span>
                </div>
              )
            })}
            <div style={s('font-size:9px;color:#5d6a85;margin-top:10px;')}>Portfolio weight minus {d.benchmark} weight, in pp.</div>
          </div>
          <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;')}>
            <div style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;margin-bottom:13px;")}>Concentration <span style={s("font-family:'IBM Plex Mono';font-weight:400;color:#5d6a85;text-transform:none;letter-spacing:0;")}>· stock sleeve</span></div>
            <div style={s('display:flex;flex-direction:column;gap:11px;')}>
              {[['Stock picks', c.holdings, 'Number of individual stock positions.'], ['Effective # names', c.effective_n, 'Inverse of the Herfindahl-Hirschman Index (HHI).'], ['Top-5 weight', c.top5 + '%', 'Combined weight of the top 5 largest positions.'], ['HHI', c.hhi, 'Herfindahl-Hirschman Index, a measure of portfolio concentration.']].map((r, i) => (
                <div key={i} title={r[2]} style={s('display:flex;justify-content:space-between;align-items:baseline;')}><span style={s('font-size:11px;color:#9aa7c2;')}>{r[0]}</span><span style={s("font-family:'IBM Plex Mono';font-size:15px;color:#e8edf7;")}>{r[1]}</span></div>
              ))}
            </div>
          </div>
        </div>
      </React.Fragment>
    )
  }

  // ---------- What-if sandbox: live client-side risk math on the shipped covariance ----------
  _renderWhatifTab(key) {
    const st = this.state
    const d = st.whatif[key]
    if (!d || d === 'loading') return this._optimizeMsg('Loading book and covariance matrix…')
    if (d === 'error') return this._optimizeMsg('Could not load what-if inputs.')

    const adj = st.whatifAdj[key] || {}
    const dest = st.whatifDest
    const cur = d.stocks.map((x) => x.w * 100)
    const now_ = d.stocks.map((x, i) => (adj[x.t] !== undefined ? adj[x.t] : cur[i]))
    const sumDelta = now_.reduce((a, w, i) => a + (w - cur[i]), 0)
    let o = d.overlay * 100, cash = 0
    if (dest === 'overlay') o -= sumDelta; else cash = -sumDelta
    const infeasible = (dest === 'overlay' ? o : cash) < -0.05

    const base = this._wfStats(d, cur.map((w) => w / 100), d.overlay, 0)
    const live = this._wfStats(d, now_.map((w) => w / 100), Math.max(o, 0) / 100, Math.max(cash, 0) / 100)
    const changed = d.stocks.map((x, i) => ({ ...x, i, from: cur[i], to: now_[i], delta: now_[i] - cur[i] }))
      .filter((x) => Math.abs(x.delta) >= 0.05).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    const rcTop = d.stocks.map((x, i) => ({ t: x.t, rc: live.rc[i], active: now_[i] - (1 - Math.max(o, 0) / 100) * x.bench_w * 100 }))
      .sort((a, b) => Math.abs(b.rc) - Math.abs(a.rc)).slice(0, 6)
    const maxRc = Math.max.apply(null, rcTop.map((r) => Math.abs(r.rc)).concat([1]))

    const cmp = (b2, l2, dp, pct, goodDown) => {
      const same = Math.abs(l2 - b2) < Math.pow(10, -dp) / 2
      const color = same ? '#cdd6e8' : (goodDown === null ? '#cdd6e8' : ((l2 < b2) === goodDown ? '#21d07a' : '#ff5666'))
      return { from: b2.toFixed(dp) + (pct ? '%' : ''), to: l2.toFixed(dp) + (pct ? '%' : ''), color, same }
    }
    const kpis = [
      { l: 'Tracking Error', ...cmp(base.te, live.te, 2, true, true), sub: 'ex-ante, ann.', tooltip: 'Realized standard deviation of active returns.' },
      { l: 'Active Share', ...cmp(base.as, live.as, 1, true, null), sub: 'look-through', tooltip: 'Percentage of the portfolio that differs from the benchmark.' },
      { l: 'Beta vs ' + d.benchmark, ...cmp(base.beta, live.beta, 2, false, null), sub: '3Y daily cov', tooltip: 'Portfolio beta relative to the benchmark.' },
      { l: 'Portfolio Vol', ...cmp(base.vol, live.vol, 1, true, true), sub: 'total, ann.', tooltip: 'Total annualized volatility.' },
    ]
    const nCells = d.stocks.length
    const cell = Math.max(9, Math.min(15, Math.floor(430 / nCells)))
    let lastGroup = null

    return (
      <React.Fragment>
        {/* KPI strip: baseline -> live */}
        <div style={s('display:grid;grid-template-columns:repeat(4,1fr);gap:11px;')}>
          {kpis.map((t, i) => (
            <div key={i} title={t.tooltip} style={{ ...s('background:#0e1422;border:1px solid #1d2840;border-radius:0 8px 8px 0;padding:11px 13px;'), borderLeft: '3px solid ' + (i < 2 ? '#5a93f9' : '#2a3a5c') }}>
              <div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")}>{t.l}</div>
              <div style={s("font-family:'IBM Plex Mono';font-size:16px;margin-top:5px;")}>
                <span style={{ color: t.same ? '#e8edf7' : '#5d6a85' }}>{t.from}</span>
                {!t.same && <span style={{ color: '#6b7794' }}> → </span>}
                {!t.same && <span style={{ color: t.color }}>{t.to}</span>}
              </div>
              <div style={s('font-size:9px;color:#5d6a85;margin-top:2px;')}>{t.sub}</div>
            </div>
          ))}
        </div>
        {/* controls: destination + reset + feasibility */}
        <div style={s('display:flex;justify-content:space-between;align-items:center;background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:10px 14px;')}>
          <div style={s('display:flex;align-items:center;gap:9px;')}>
            <span style={s("font:600 9px 'IBM Plex Sans';letter-spacing:.07em;text-transform:uppercase;color:#6b7794;")}>Trim proceeds →</span>
            {[['overlay', d.benchmark + ' overlay'], ['cash', 'Cash']].map(([k2, label]) => (
              <span key={k2} onClick={() => this.setState({ whatifDest: k2 })} style={{ ...s("padding:4px 11px;border-radius:5px;cursor:pointer;font:600 10px 'IBM Plex Sans';"), background: dest === k2 ? '#13203a' : 'transparent', color: dest === k2 ? '#5a93f9' : '#6b7794', border: dest === k2 ? '1px solid #28406e' : '1px solid #1d2840' }}>{label}</span>
            ))}
            <span style={s("font-family:'IBM Plex Mono';font-size:10px;color:#5d6a85;margin-left:6px;")}>overlay {Math.max(o, 0).toFixed(1)}% · cash {Math.max(cash, 0).toFixed(1)}%</span>
            {infeasible && <span style={s("font:600 10px 'IBM Plex Sans';color:#ff5666;")}>adds exceed available {dest === 'overlay' ? 'overlay' : 'cash'} — trim elsewhere</span>}
          </div>
          <span onClick={() => this.setState((s2) => ({ whatifAdj: { ...s2.whatifAdj, [key]: {} } }))} style={s("font:600 10px 'IBM Plex Sans';color:#9aa7c2;background:#13203a;border:1px solid #24345a;border-radius:5px;padding:4px 11px;cursor:pointer;")}>Reset</span>
        </div>
        <div style={s('display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:14px;align-items:start;')}>
          {/* sliders, grouped by UOIG sector */}
          <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;')}>
            <div style={s('display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;')}>
              <span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;")}>Position Weights</span>
              <span style={s('font-size:9.5px;color:#5d6a85;')}>drag to restage · grey tick = benchmark weight</span>
            </div>
            {d.stocks.map((x, i) => {
              const head = x.group !== lastGroup ? (lastGroup = x.group) : null
              const max = Math.max(cur[i] * 2, cur[i] + 5, 2)
              const delta = now_[i] - cur[i]
              const benchPos = Math.min(x.bench_w * 100 / max * 100, 100)
              return (
                <React.Fragment key={x.t}>
                  {head && <div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.09em;text-transform:uppercase;color:#5d6a85;margin:11px 0 3px;")}>{head}</div>}
                  <div style={s('display:grid;grid-template-columns:52px minmax(0,1fr) 108px;gap:10px;align-items:center;padding:4px 0;')}>
                    <span style={s("font-family:'IBM Plex Mono';font-weight:500;font-size:11.5px;color:#e8edf7;")}>{x.t}</span>
                    <div style={s('position:relative;display:flex;align-items:center;')}>
                      <div style={{ ...s('position:absolute;top:-2px;width:1.5px;height:5px;background:#5d6a85;z-index:1;'), left: benchPos + '%' }}></div>
                      <input type="range" min={0} max={max} step={0.1} value={now_[i]}
                        onChange={(e) => { const v2 = parseFloat(e.target.value); this.setState((s2) => ({ whatifAdj: { ...s2.whatifAdj, [key]: { ...(s2.whatifAdj[key] || {}), [x.t]: v2 } } })) }}
                        style={{ width: '100%', accentColor: Math.abs(delta) >= 0.05 ? '#5a93f9' : '#2a3a5c', height: '3px' }} />
                    </div>
                    <span style={s("font-family:'IBM Plex Mono';font-size:10.5px;text-align:right;color:#cdd6e8;")}>
                      {now_[i].toFixed(1)}%
                      <span style={{ color: Math.abs(delta) < 0.05 ? '#3c465e' : (delta > 0 ? '#21d07a' : '#ff5666') }}> {Math.abs(delta) < 0.05 ? '·' : this._sign(delta, 1)}</span>
                    </span>
                  </div>
                </React.Fragment>
              )
            })}
          </div>
          <div style={s('display:flex;flex-direction:column;gap:14px;')}>
            {/* staged trades */}
            <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;')}>
              <div style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;margin-bottom:11px;")}>Staged Trades</div>
              {!changed.length && <div style={s("font:400 11px/1.6 'IBM Plex Sans';color:#5d6a85;")}>No changes staged. Drag a slider to model a trade.</div>}
              {changed.map((x) => (
                <div key={x.t} style={s('display:grid;grid-template-columns:38px 52px 1fr auto;gap:9px;align-items:center;padding:6px 0;border-bottom:1px solid #131c2f;')}>
                  <span style={{ ...s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;border-radius:4px;padding:2px 0;text-align:center;"), color: x.delta > 0 ? '#21d07a' : '#ff5666', border: '1px solid ' + (x.delta > 0 ? '#1a5c3d' : '#6e2a35') }}>{x.delta > 0 ? 'BUY' : 'SELL'}</span>
                  <span style={s("font-family:'IBM Plex Mono';font-weight:500;font-size:11.5px;color:#e8edf7;")}>{x.t}</span>
                  <span style={s("font-family:'IBM Plex Mono';font-size:10.5px;color:#8290ad;")}>{x.from.toFixed(1)}% → {x.to.toFixed(1)}%</span>
                  <span style={{ ...s("font-family:'IBM Plex Mono';font-size:11px;text-align:right;"), color: x.delta > 0 ? '#21d07a' : '#ff5666' }}>{this._kdSigned(x.delta / 100 * d.invested_value)}</span>
                </div>
              ))}
              {changed.length > 0 && <div style={s("display:flex;justify-content:space-between;margin-top:9px;font-family:'IBM Plex Mono';font-size:10px;color:#6b7794;")}><span>{changed.length} trades</span><span>turnover {(changed.reduce((a, x) => a + Math.abs(x.delta), 0) / 2).toFixed(1)}%</span></div>}
            </div>
            {/* live active-risk contributors */}
            <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;')}>
              <div style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;margin-bottom:11px;")}>Active Risk · live</div>
              {rcTop.map((r) => (
                <div key={r.t} style={s('display:grid;grid-template-columns:52px 1fr 44px;gap:9px;align-items:center;padding:5px 0;')}>
                  <span style={s("font-family:'IBM Plex Mono';font-weight:500;font-size:11.5px;color:#e8edf7;")}>{r.t}</span>
                  <div style={s('display:flex;align-items:center;')}><span style={{ ...s('height:6px;border-radius:3px;opacity:.8;'), width: Math.max(4, Math.abs(r.rc) / maxRc * 100) + '%', background: r.rc >= 0 ? (r.active >= 0 ? '#21d07a' : '#ff5666') : '#5d6a85' }}></span></div>
                  <span style={s("font-family:'IBM Plex Mono';font-size:11px;text-align:right;color:#cdd6e8;")}>{Math.round(r.rc)}%</span>
                </div>
              ))}
              <div style={s('font-size:9px;color:#5d6a85;margin-top:8px;')}>Share of ex-ante tracking variance. Recomputes as you drag.</div>
            </div>
          </div>
        </div>
        {/* correlation heatmap */}
        <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;overflow-x:auto;')}>
          <div style={s('display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;')}>
            <span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;")}>Correlation · 3Y daily</span>
            <span style={s('font-size:9.5px;color:#5d6a85;')}><span style={s('color:#ff5666;')}>■</span> +1 · <span style={s('color:#21d07a;')}>■</span> −1 · grouped by sector</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '46px repeat(' + nCells + ', ' + cell + 'px)', gap: '1px', width: 'fit-content' }}>
            <div></div>
            {d.stocks.map((x) => (<div key={'h' + x.t} title={x.t} style={{ ...s('font-size:7.5px;color:#6b7794;overflow:hidden;'), fontFamily: "'IBM Plex Mono'", writingMode: 'vertical-rl', height: '30px', lineHeight: cell + 'px' }}>{x.t}</div>))}
            {d.stocks.map((x, i2) => (
              <React.Fragment key={'r' + x.t}>
                <div style={{ ...s('font-size:8.5px;color:#8290ad;text-align:right;padding-right:5px;'), fontFamily: "'IBM Plex Mono'", lineHeight: cell + 'px' }}>{x.t}</div>
                {d.corr[i2].map((c, j2) => (
                  <div key={j2} title={x.t + ' × ' + d.stocks[j2].t + ': ' + c.toFixed(2)}
                    style={{ width: cell + 'px', height: cell + 'px', borderRadius: '1px', background: i2 === j2 ? '#2a3a5c' : (c >= 0 ? 'rgba(255,86,102,' + (c * 0.85).toFixed(2) + ')' : 'rgba(33,208,122,' + (-c * 0.85).toFixed(2) + ')') }}></div>
                ))}
              </React.Fragment>
            ))}
          </div>
        </div>
      </React.Fragment>
    )
  }

  // ---------- Black-Litterman optimizer tab ----------
  _renderOptimizerTab(key) {
    const st = this.state
    const res = st.optResult[key]
    const vmap = st.optViews[key] || {}
    const setView = (t, patch) => this.setState((s2) => {
      const cown = { ...(s2.optViews[key] || {}) }
      cown[t] = { q: '', conf: 'med', ...(cown[t] || {}), ...patch }
      if (patch.q === '' && !patch.conf) delete cown[t]
      return { optViews: { ...s2.optViews, [key]: cown } }
    })
    const params = (
      <div style={s('display:flex;justify-content:space-between;align-items:center;background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:10px 14px;')}>
        <div style={s('display:flex;align-items:center;gap:16px;')}>
          {[['Max position', 'optCap', '%'], ['Benchmark ERP', 'optErp', '%/yr']].map(([label, sk, unit]) => (
            <label key={sk} style={s("display:flex;align-items:center;gap:7px;font:600 9px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;color:#6b7794;")}>
              {label}
              <input value={st[sk]} onChange={(e) => this.setState({ [sk]: e.target.value })}
                style={{ ...s("width:44px;background:#0a0f1a;border:1px solid #1d2840;border-radius:5px;color:#e8edf7;padding:4px 7px;font-size:11px;text-align:right;outline:none;"), fontFamily: "'IBM Plex Mono'" }} />
              <span style={s('color:#5d6a85;text-transform:none;letter-spacing:0;')}>{unit}</span>
            </label>
          ))}
          {res && res !== 'loading' && res !== 'error' && <span style={s("font-family:'IBM Plex Mono';font-size:10px;color:#5d6a85;")}>rf {res.rf}% · τ 0.05 · long-only · overlay fixed at {res.overlay}%</span>}
        </div>
        <span onClick={() => this._runSolve(key)} style={s("font:600 10.5px 'IBM Plex Sans';color:#0a0f1a;background:#5a93f9;border-radius:6px;padding:6px 16px;cursor:pointer;")}>{res === 'loading' ? 'Solving…' : 'Solve'}</span>
      </div>
    )
    if (!res || res === 'loading') return <React.Fragment>{params}{this._optimizeMsg('Running the Black-Litterman solve — implied returns, posterior tilt, constrained frontier…')}</React.Fragment>
    if (res === 'error') return <React.Fragment>{params}{this._optimizeMsg('Solve failed. Check inputs and try again.')}</React.Fragment>

    const sb = res.stats.before, sa = res.stats.after
    const stat = (label, b2, a2, unit, goodUp) => {
      const same = Math.abs(a2 - b2) < 0.005
      const color = same ? '#cdd6e8' : (goodUp === null ? '#cdd6e8' : ((a2 > b2) === goodUp ? '#21d07a' : '#ff5666'))
      return { label, b: b2 + (unit || ''), a: a2 + (unit || ''), color, same }
    }
    const stats = [
      stat('Exp Return', sb.ret, sa.ret, '%', true),
      stat('Volatility', sb.vol, sa.vol, '%', false),
      stat('Sharpe', sb.sharpe, sa.sharpe, '', true),
      stat('Tracking Err', sb.te, sa.te, '%', null),
      stat('Beta', sb.beta, sa.beta, '', null),
    ]
    const trades = res.rows.filter((r) => Math.abs(r.delta) >= 0.1)
    return (
      <React.Fragment>
        {params}
        <div style={s('display:grid;grid-template-columns:repeat(5,1fr) auto;gap:11px;')}>
          {stats.map((t, i) => (
            <div key={i} style={s('background:#0e1422;border:1px solid #1d2840;border-radius:8px;padding:10px 13px;')}>
              <div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;white-space:nowrap;")}>{t.label}</div>
              <div style={s("font-family:'IBM Plex Mono';font-size:14.5px;margin-top:5px;")}>
                <span style={{ color: '#5d6a85' }}>{t.b}</span><span style={{ color: '#6b7794' }}> → </span><span style={{ color: t.color }}>{t.a}</span>
              </div>
            </div>
          ))}
          <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:8px;padding:10px 13px;')}>
            <div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;")}>Turnover</div>
            <div style={s("font-family:'IBM Plex Mono';font-size:14.5px;margin-top:5px;color:#f4a531;")}>{res.turnover}%</div>
          </div>
        </div>
        <div style={s('display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:14px;align-items:start;')}>
          {/* views editor */}
          <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;')}>
            <div style={s('display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;')}>
              <span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;")}>Club Views</span>
              <span style={s('font-size:9.5px;color:#5d6a85;')}>expected out/under-performance vs {res.benchmark}, %/yr → Solve</span>
            </div>
            <div style={s("display:grid;grid-template-columns:50px 1fr 66px 66px 66px 96px;gap:8px;font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;padding-bottom:6px;border-bottom:1px solid #1d2840;")}>
              <span>Ticker</span><span>Name</span><span style={s('text-align:right;')}>Implied</span><span style={s('text-align:right;')}>Posterior</span><span style={s('text-align:right;')}>View %</span><span style={s('text-align:center;')}>Confidence</span>
            </div>
            {res.rows.slice().sort((a, b) => b.w_cur - a.w_cur).map((r) => {
              const v2 = vmap[r.t] || { q: '', conf: 'med' }
              return (
                <div key={r.t} style={s('display:grid;grid-template-columns:50px 1fr 66px 66px 66px 96px;gap:8px;align-items:center;padding:5px 0;border-bottom:1px solid #131c2f;')}>
                  <span style={s("font-family:'IBM Plex Mono';font-weight:500;font-size:11.5px;color:#e8edf7;")}>{r.t}</span>
                  <span style={s("font:400 10px 'IBM Plex Sans';color:#8290ad;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")}>{r.name}</span>
                  <span style={s("font-family:'IBM Plex Mono';font-size:10.5px;text-align:right;color:#6b7794;")}>{r.implied}%</span>
                  <span style={{ ...s("font-family:'IBM Plex Mono';font-size:10.5px;text-align:right;"), color: Math.abs(r.posterior - r.implied) > 0.05 ? '#5a93f9' : '#cdd6e8' }}>{r.posterior}%</span>
                  <input value={v2.q} placeholder="—" onChange={(e) => setView(r.t, { q: e.target.value.replace(/[^0-9.\-]/g, '') })}
                    style={{ ...s('width:100%;background:#0a0f1a;border:1px solid #1d2840;border-radius:4px;color:#e8edf7;padding:3px 6px;font-size:10.5px;text-align:right;outline:none;box-sizing:border-box;'), fontFamily: "'IBM Plex Mono'" }} />
                  <div style={s('display:flex;gap:2px;justify-content:center;')}>
                    {['low', 'med', 'high'].map((c2) => (
                      <span key={c2} onClick={() => setView(r.t, { conf: c2 })} style={{ ...s("padding:2px 6px;border-radius:3px;cursor:pointer;font:600 8px 'IBM Plex Sans';text-transform:uppercase;"), background: v2.conf === c2 && v2.q !== '' ? '#13203a' : 'transparent', color: v2.conf === c2 && v2.q !== '' ? '#5a93f9' : '#3c465e', border: '1px solid ' + (v2.conf === c2 && v2.q !== '' ? '#28406e' : '#1d2840') }}>{c2[0]}</span>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
          <div style={s('display:flex;flex-direction:column;gap:14px;')}>
            {/* efficient frontier */}
            <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;')}>
              <div style={s('display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;')}>
                <span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;")}>Constrained Frontier</span>
                <div style={s("display:flex;gap:11px;font:500 9.5px 'IBM Plex Sans';")}>
                  <span style={s('color:#8290ad;')}>● current</span><span style={s('color:#21d07a;')}>● proposed</span><span style={s('color:#f4a531;')}>● min-var</span>
                </div>
              </div>
              {this._frontierChart(res)}
            </div>
            {/* proposed trades */}
            <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:15px;')}>
              <div style={s('display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;')}>
                <span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;")}>Proposed Trades</span>
                <span style={s('font-size:9.5px;color:#5d6a85;')}>max-Sharpe portfolio · {res.n_views} view{res.n_views === 1 ? '' : 's'}</span>
              </div>
              {trades.map((r) => (
                <div key={r.t} style={s('display:grid;grid-template-columns:38px 52px 1fr auto;gap:9px;align-items:center;padding:5px 0;border-bottom:1px solid #131c2f;')}>
                  <span style={{ ...s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;border-radius:4px;padding:2px 0;text-align:center;"), color: r.delta > 0 ? '#21d07a' : '#ff5666', border: '1px solid ' + (r.delta > 0 ? '#1a5c3d' : '#6e2a35') }}>{r.delta > 0 ? 'BUY' : 'SELL'}</span>
                  <span style={s("font-family:'IBM Plex Mono';font-weight:500;font-size:11.5px;color:#e8edf7;")}>{r.t}</span>
                  <span style={s("font-family:'IBM Plex Mono';font-size:10.5px;color:#8290ad;")}>{r.w_cur.toFixed(1)}% → {r.w_prop.toFixed(1)}%</span>
                  <span style={{ ...s("font-family:'IBM Plex Mono';font-size:11px;text-align:right;"), color: r.delta > 0 ? '#21d07a' : '#ff5666' }}>{this._kdSigned(r.dollars)}</span>
                </div>
              ))}
              {!trades.length && <div style={s("font:400 11px/1.6 'IBM Plex Sans';color:#5d6a85;")}>The current book is already on the constrained frontier.</div>}
            </div>
          </div>
        </div>
      </React.Fragment>
    )
  }

  _frontierChart(res) {
    const W = 520, H = 210, ml = 40, mr = 12, mt = 10, mb = 26
    const pts = res.frontier.concat([res.points.current, res.points.proposed, res.points.minvar])
    const xs = pts.map((p) => p.vol), ys = pts.map((p) => p.ret)
    const x0 = Math.min.apply(null, xs) - 0.6, x1 = Math.max.apply(null, xs) + 0.6
    const y0 = Math.min.apply(null, ys) - 0.5, y1 = Math.max.apply(null, ys) + 0.5
    const X = (v) => ml + (v - x0) / ((x1 - x0) || 1) * (W - ml - mr)
    const Y = (v) => mt + (1 - (v - y0) / ((y1 - y0) || 1)) * (H - mt - mb)
    const path = res.frontier.map((p, i) => (i ? 'L' : 'M') + X(p.vol).toFixed(1) + ',' + Y(p.ret).toFixed(1)).join(' ')
    const ticksX = [0, 1, 2, 3].map((i) => x0 + (x1 - x0) * i / 3)
    const ticksY = [0, 1, 2, 3].map((i) => y0 + (y1 - y0) * i / 3)
    const dot = (p, color, label, anchor) => [
      React.createElement('circle', { key: 'c' + label, cx: X(p.vol), cy: Y(p.ret), r: 4, style: { fill: color, stroke: '#0e1422', strokeWidth: 1.5 } }),
      React.createElement('text', { key: 't' + label, x: X(p.vol) + (anchor === 'end' ? -7 : 7), y: Y(p.ret) + 3, textAnchor: anchor || 'start', style: { fill: color, font: "600 8.5px 'IBM Plex Sans'" } }, label),
    ]
    return React.createElement('svg', { viewBox: '0 0 ' + W + ' ' + H, style: { width: '100%', display: 'block' } },
      ticksY.map((t, i) => React.createElement('g', { key: 'gy' + i }, [
        React.createElement('line', { key: 'l', x1: ml, x2: W - mr, y1: Y(t), y2: Y(t), style: { stroke: '#16203a', strokeWidth: 1 } }),
        React.createElement('text', { key: 't', x: ml - 5, y: Y(t) + 3, textAnchor: 'end', style: { fill: '#5d6a85', font: "8.5px 'IBM Plex Mono'" } }, t.toFixed(1) + '%'),
      ])).concat(ticksX.map((t, i) => React.createElement('text', { key: 'gx' + i, x: X(t), y: H - 8, textAnchor: 'middle', style: { fill: '#5d6a85', font: "8.5px 'IBM Plex Mono'" } }, t.toFixed(1) + '%')))
        .concat([
          React.createElement('text', { key: 'xl', x: (ml + W - mr) / 2, y: H - 0.5, textAnchor: 'middle', style: { fill: '#3c465e', font: "600 7.5px 'IBM Plex Sans'", letterSpacing: '.08em' } }, 'VOLATILITY (ANN)'),
          React.createElement('path', { key: 'fr', d: path, style: { fill: 'none', stroke: '#5a93f9', strokeWidth: 1.8, strokeLinecap: 'round' } }),
        ])
        .concat(dot(res.points.minvar, '#f4a531', 'min-var', 'start'))
        .concat(dot(res.points.current, '#8290ad', 'current', 'start'))
        .concat(dot(res.points.proposed, '#21d07a', 'proposed', 'end')))
  }

  _renderSector(v) {
    const sec = v.sec
    return (
      <div style={s('padding:16px;display:flex;flex-direction:column;gap:13px;')}>
        <div onClick={() => this._go('sectors')} style={s("display:inline-flex;align-items:center;gap:6px;font:500 11px 'IBM Plex Sans';color:#6b7794;cursor:pointer;width:fit-content;")}>‹ Sectors</div>
        <div style={s('display:flex;justify-content:space-between;align-items:flex-start;')}>
          <div><div style={s("font:600 22px 'IBM Plex Sans';color:#e8edf7;")}>{sec.name}</div></div>
          <div style={s('text-align:right;')}><div style={s("font-family:'IBM Plex Mono';font-size:24px;color:#e8edf7;")}>{sec.shareStr}</div><div style={{ ...s("font-family:'IBM Plex Mono';font-size:11px;margin-top:2px;"), color: sec.retColor }}>MTD {sec.ret}</div></div>
        </div>
        {/* sector vs iShares benchmarks + weekly movers */}
        <div style={s('display:flex;justify-content:space-between;align-items:center;')}>
          <span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;")}>Sector vs iShares · indexed return</span>
          <div style={s('display:flex;align-items:center;gap:3px;background:#0a0f1a;border:1px solid #1d2840;border-radius:8px;padding:3px;')}>{v.secPeriods.map((p) => (<span key={p.k} onClick={p.on} style={{ ...s("padding:4px 9px;border-radius:5px;cursor:pointer;font-size:10px;font-family:'IBM Plex Mono';"), fontWeight: p.weight, background: p.bg, color: p.color }}>{p.k}</span>))}</div>
        </div>
        {v.secState === 'ready' ? (
          <React.Fragment>
            <div style={{ ...s('display:grid;gap:10px;'), gridTemplateColumns: 'repeat(' + v.secKpis.length + ',minmax(0,1fr))' }}>
              {v.secKpis.map((k, i) => (
                <div key={i} style={{ ...s('background:#0e1422;border:1px solid #1d2840;border-radius:0 8px 8px 0;padding:10px 12px;'), borderLeft: '3px solid ' + k.color }}>
                  <div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;color:#6b7794;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")}>{k.label}</div>
                  <div style={{ ...s("font-family:'IBM Plex Mono';font-size:18px;margin-top:4px;"), color: k.valColor }}>{k.val}</div>
                </div>
              ))}
            </div>
            <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:14px;')}>
              <div style={s('display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;')}>
                <span style={s("font:500 10px 'IBM Plex Sans';color:#6b7794;")}>Indexed to 0% at the start of {v.secPeriod}</span>
                <div style={s("display:flex;gap:13px;font:500 10px 'IBM Plex Sans';flex-wrap:wrap;")}>{v.secChartLegend.map((l, i) => (<span key={i} style={{ color: l.color }}>{l.mark} {l.label}</span>))}</div>
              </div>
              <div style={s('height:190px;')}>{v.secChartEl}</div>
            </div>
            <div style={s('display:grid;grid-template-columns:1fr 1fr;gap:11px;')}>
              {[{ t: 'Leaders · 1 week', rows: v.secTop }, { t: 'Laggards · 1 week', rows: v.secBottom }].map((col, ci) => (
                <div key={ci} style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:12px 13px;')}>
                  <div style={s("font:600 9px 'IBM Plex Sans';letter-spacing:.07em;text-transform:uppercase;color:#6b7794;margin-bottom:6px;")}>{col.t}</div>
                  {col.rows.map((m, i) => (
                    <div key={i} onClick={m.on} className="dc-row" style={s('display:flex;align-items:center;gap:9px;padding:7px 0;border-bottom:1px solid #131c2f;cursor:pointer;')}>
                      <span style={s("font-family:'IBM Plex Mono';font-weight:500;font-size:12px;color:#e8edf7;width:54px;")}>{m.t}</span>
                      <span style={s("font:400 10px 'IBM Plex Sans';color:#8290ad;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;")}>{m.n}</span>
                      <span style={{ ...s("font-family:'IBM Plex Mono';font-size:12px;"), color: m.color }}>{m.pct}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </React.Fragment>
        ) : (
          <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:30px;display:flex;justify-content:center;color:#5d6a85;font:500 11px \'IBM Plex Sans\';')}>{v.secState === 'error' ? 'Could not load sector comparison data.' : 'Loading sector comparison…'}</div>
        )}
        {/* full composition + holdings (unchanged, below the comparison) */}
        <div style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;margin-top:4px;")}>Composition</div>
        <div style={{ ...s('display:grid;gap:11px;'), gridTemplateColumns: 'repeat(' + (1 + sec.wTiles.length) + ',1fr)' }}>
          <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:8px;padding:13px;')}><div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;color:#6b7794;")}>Holdings</div><div style={s("font-family:'IBM Plex Mono';font-size:18px;color:#e8edf7;margin-top:5px;")}>{sec.count}</div></div>
          {sec.wTiles.map((t, i) => (
            <div key={i} style={s('background:#0e1422;border:1px solid #1d2840;border-radius:8px;padding:13px;')}><div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;color:#6b7794;")}>{t.label}</div><div style={{ ...s("font-family:'IBM Plex Mono';font-size:18px;margin-top:5px;"), color: t.color }}>{t.val}</div></div>
          ))}
        </div>
        <div style={s('background:#0e1422;border:1px solid #1d2840;border-radius:9px;overflow:hidden;')}>
          <div style={s("padding:10px 14px;border-bottom:1px solid #1d2840;font:600 10px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#7e8aa6;")}>Holdings in {sec.name}</div>
          <div style={s("display:grid;grid-template-columns:74px 1fr 64px 70px 92px 72px 72px;gap:8px;padding:8px 14px;border-bottom:1px solid #1d2840;font:600 8.5px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;color:#6b7794;")}><span>Ticker</span><span>Name</span><span style={s('text-align:right;')}>Fund</span><span style={s('text-align:right;')}>Wt</span><span style={s('text-align:right;')}>Price</span><span style={s('text-align:right;')}>Day</span><span style={s('text-align:right;')}>MTD</span></div>
          {v.secRows.map((r) => (
            <div key={r.rk} onClick={r.open} className="dc-row" style={s('display:grid;grid-template-columns:74px 1fr 64px 70px 92px 72px 72px;gap:8px;align-items:center;padding:7.5px 14px;border-bottom:1px solid #131c2f;font-size:11px;cursor:pointer;')}>
              <span style={s("font-family:'IBM Plex Mono';font-weight:600;color:#e8edf7;")}>{r.t}</span>
              <span style={s('color:#9aa7c2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;')}>{r.n}</span>
              <span style={{ ...s("text-align:right;font:500 9px 'IBM Plex Mono';"), color: r.fundColor }}>{r.fundTag}</span>
              <span style={s("font-family:'IBM Plex Mono';text-align:right;color:#cdd6e8;")}>{r.wStr}</span>
              <span style={s("font-family:'IBM Plex Mono';text-align:right;color:#cdd6e8;")}>{r.pxStr}</span>
              <span style={{ ...s("font-family:'IBM Plex Mono';text-align:right;"), color: r.dayColor }}>{r.dayStr}</span>
              <span style={{ ...s("font-family:'IBM Plex Mono';text-align:right;"), color: r.mtdColor }}>{r.mtdStr}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  // Dedicated full-page Assistant tab — same chat state/backend as the Ask-Claude
  // popup (this.state.chat, _send, _runAgent), just laid out to fill the main pane
  // instead of a floating widget, for longer research sessions.
  _renderAssistant(v) {
    return (
      <div style={s('height:100%;display:flex;flex-direction:column;')}>
        <div style={s('display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid #1d2840;flex:0 0 auto;')}>
          <div style={s('display:flex;align-items:center;gap:10px;')}>
            <span style={s('font-size:18px;color:#5a4fd6;')}>✦</span>
            <div>
              <div style={s("font:600 14px 'IBM Plex Sans';color:#e8edf7;")}>Assistant</div>
              <div style={s("font-size:10.5px;color:#6b7794;margin-top:1px;")}>Your research co-pilot — knows the live portfolio</div>
            </div>
          </div>
          <div style={s('display:flex;align-items:center;gap:9px;')}>
            <span style={s('font-size:9px;color:#7a6fb5;text-transform:uppercase;letter-spacing:.06em;')}>Context</span>
            <span style={s('font-size:10.5px;color:#c3b9ff;background:#15112c;border:1px solid #2c2550;border-radius:6px;padding:4px 10px;')}>{v.ctxLabel}</span>
            <span onClick={() => this.setState({ chat: [] })} className="dc-hover" style={s('font-size:10px;color:#7a6fb5;border:1px solid #2c2550;border-radius:6px;padding:5px 10px;cursor:pointer;')}>Clear</span>
          </div>
        </div>
        <div ref={this.chatRef} style={s('flex:1;min-height:0;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:13px;max-width:760px;width:100%;margin:0 auto;')}>
          {v.chatEmpty && (
            <div style={s('display:flex;flex-direction:column;align-items:center;text-align:center;gap:9px;margin:auto 0;color:#6b7794;padding:0 6px;')}>
              <span style={s('font-size:30px;color:#5a4fd6;')}>✦</span>
              <div style={s("font:600 14px 'IBM Plex Sans';color:#b8aef0;")}>Your research co-pilot</div>
              <div style={s('font-size:12px;line-height:1.6;max-width:420px;')}>Ask anything about a fund, holding, or sector — it knows the live portfolio and can read the terminal's own code.</div>
            </div>
          )}
          {v.chatMsgs.map((m) => (
            <div key={m.key} style={{ ...s('padding:10px 13px;font-size:12.5px;line-height:1.6;white-space:pre-wrap;'), alignSelf: m.align, maxWidth: m.maxw, background: m.bg, border: '1px solid ' + m.border, borderRadius: m.radius, color: m.color }}>{m.body}</div>
          ))}
          {v.loading && (
            <div style={s('align-self:flex-start;display:flex;align-items:center;gap:7px;color:#7a6fb5;font-size:11px;')}><span style={s('display:flex;gap:3px;')}><span style={s('width:5px;height:5px;border-radius:50%;background:#7a6fb5;animation:pulseDot 1.4s infinite;')}></span><span style={s('width:5px;height:5px;border-radius:50%;background:#7a6fb5;animation:pulseDot 1.4s infinite .2s;')}></span><span style={s('width:5px;height:5px;border-radius:50%;background:#7a6fb5;animation:pulseDot 1.4s infinite .4s;')}></span></span>Claude is analyzing…</div>
          )}
        </div>
        <div style={s('padding:14px 20px 20px;flex:0 0 auto;max-width:760px;width:100%;margin:0 auto;box-sizing:border-box;')}>
          <div onClick={() => this._runAgent()} style={{ ...s("display:flex;align-items:center;justify-content:center;gap:7px;margin-bottom:11px;padding:9px;border-radius:8px;font:600 11px 'IBM Plex Sans';letter-spacing:.03em;cursor:pointer;"), background: this.state.agentBusy ? '#1a1533' : 'linear-gradient(135deg,#5a4fd6,#3a31a8)', color: this.state.agentBusy ? '#7a6fb5' : '#fff', cursor: this.state.agentBusy ? 'default' : 'pointer' }}><span style={s('font-size:11px;')}>▶</span>{this.state.agentBusy ? 'Running market analysis…' : 'Run market analysis'}</div>
          <div style={s('display:flex;align-items:flex-end;gap:9px;background:#0e1422;border:1px solid #2c2550;border-radius:10px;padding:10px 12px;')}>
            <input value={v.input} onChange={(e) => this.setState({ input: e.target.value })} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._send() } }} placeholder={'Ask about ' + v.ctxShort + '…'} style={s("flex:1;background:transparent;border:none;outline:none;color:#e8edf7;font:400 12.5px 'IBM Plex Sans';")} />
            <span onClick={() => this._send()} style={{ ...s('width:29px;height:29px;border-radius:7px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:15px;cursor:pointer;flex:0 0 auto;'), background: v.sendBg }}>↑</span>
          </div>
        </div>
      </div>
    )
  }

  // ---------- view-model ----------
  renderVals() {
    const st = this.state, F = this.funds, keys = this.fundKeys
    const fundA = keys[0], fundB = keys[1]
    const v = {}
    const mkt = this._marketStatus()
    v.marketOpen = mkt.open
    v.asOf = 'AS OF ' + mkt.date
    v.isDashboard = st.view === 'dashboard'; v.isStocks = st.view === 'stocks'
    v.isSectors = st.view === 'sectors'; v.isStock = st.view === 'stock'; v.isSector = st.view === 'sector'
    v.isOptimize = st.view === 'optimize'; v.isAssistant = st.view === 'assistant'
    v.isCoverage = st.view === 'coverage'
    v.fundAName = F[fundA].name; v.fundBName = F[fundB].name

    const isAnalyst = st.auth && ['member', 'analyst'].includes(st.auth.role)
    const navDef = [
      ...(isAnalyst ? [['coverage', 'My Coverage', 'coverage']] : []),
      ['inbox', 'Inbox', 'inbox'],
      ['funds', 'Funds', 'dashboard'], ['stocks', 'Stocks', 'stocks'], ['sectors', 'Sectors', 'sectors'], ['optimize', 'Optimize', 'optimize'], ['assistant', 'Assistant', 'assistant'],
    ]
    const activeMap = { dashboard: ['funds'], stocks: ['stocks'], sectors: ['sectors'], stock: ['stocks'], sector: ['sectors'], optimize: ['optimize'], assistant: ['assistant'], coverage: ['coverage'] }
    v.nav = navDef.map(([id, label, go]) => {
      const active = id === 'inbox' ? st.view === 'inbox' : (activeMap[st.view] || []).indexOf(id) >= 0
      return { key: id, label, icon: id === 'inbox' ? '✉' : this._icon(id, active), bg: active ? '#13203a' : 'transparent', color: active ? '#5a93f9' : '#5d6a85', on: () => this._go(go) }
    })
    v.periods = ['1M', '3M', '6M', 'YTD', '1Y', '5Y'].map((p) => ({ k: p, bg: p === st.period ? '#13203a' : 'transparent', color: p === st.period ? '#cdd6e8' : '#6b7794', weight: p === st.period ? 600 : 500, on: () => this.setState({ period: p }) }))

    v.fundTabs = [['all', 'All Funds'], [fundA, F[fundA].name], [fundB, F[fundB].name]].map(([k, label]) => ({ k, label, bg: st.fund === k ? '#1b2c4d' : 'transparent', color: st.fund === k ? '#fff' : '#9aa7c2', weight: st.fund === k ? 600 : 500, on: () => this._setFund(k) }))

    const per = st.period, fk = st.fund
    const xl = { '1M': ['4W', '3W', '2W', '1W', 'NOW'], '3M': ['APR', 'MAY', 'JUN'], '6M': ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN'], 'YTD': ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN'], '1Y': ['JUL', 'SEP', 'NOV', 'JAN', 'MAR', 'JUN'], '5Y': ["'21", "'22", "'23", "'24", "'25", "'26"] }
    v.xLabels = xl[per] || []

    const fseries = st.series[`fund:${fk}:${per}`]
    if (fk === 'all') {
      v.heroTitle = 'Total Endowment · Net Asset Value'
      v.heroValue = this._kd(this.total * 1e6)
      const r = this._blend((f) => f.ret[per])
      const gain = this.total - this.total / (1 + r / 100)
      v.heroRetColor = this._col(r)
      v.heroRetText = (r >= 0 ? '▲' : '▼') + ' ' + this._sign(r, 1) + '% ' + per + ' · ' + this._kdSigned(gain * 1e6) + ' · blended α ' + this._sign(this._blend((f) => f.alpha), 1) + '% vs policy'
      const lines = []
      if (fseries && fseries.multi) fseries.multi.forEach((m, i) => lines.push({ values: m.fund.values, color: F[keys[i]].color, area: i === 0, width: 2 }))
      v.heroChartEl = this._chart('heroAll' + per, lines, 184)
      v.heroLegend = keys.map((k) => ({ mark: '●', label: F[k].name, color: F[k].color }))
      v.heroStats = [
        { l: 'Blended α', v: this._sign(this._blend((f) => f.alpha), 1) + '%', sub: 'vs policy', c: '#21d07a', tooltip: 'Active return compared to the benchmark.' },
        { l: 'Beta', v: this._blend((f) => f.beta).toFixed(2), sub: '3Y', c: '#cdd6e8', tooltip: 'Volatility compared to the market.' },
        { l: 'Sharpe', v: this._blend((f) => f.sharpe).toFixed(2), sub: 'risk-adj', c: '#cdd6e8', tooltip: 'Risk-adjusted return.' },
        { l: 'Volatility', v: this._blend((f) => f.vol).toFixed(1) + '%', sub: 'ann σ', c: '#cdd6e8', tooltip: 'Annualized standard deviation of returns.' },
        { l: 'Fwd P/E', v: this._blend((f) => f.pe).toFixed(1), sub: 'wtd', c: '#cdd6e8', tooltip: 'Forward Price-to-Earnings ratio.' },
        { l: 'Div Yield', v: this._blend((f) => f.dy).toFixed(1) + '%', sub: 'ttm', c: '#cdd6e8', tooltip: 'Dividend yield.' },
      ]
    } else {
      const f = F[fk]
      v.heroTitle = f.long; v.heroValue = this._kd(f.aum * 1e6)
      const r = f.ret[per] || 0, gain = f.aum - f.aum / (1 + r / 100)
      v.heroRetColor = this._col(r)
      v.heroRetText = (r >= 0 ? '▲' : '▼') + ' ' + this._sign(r, 1) + '% ' + per + ' · ' + this._kdSigned(gain * 1e6) + ' · α ' + this._sign(f.alpha, 1) + '% vs ' + f.benchShort
      const lines = []
      if (fseries && fseries.fund) {
        lines.push({ values: fseries.fund.values, color: f.color, area: true })
        if (fseries.bench && fseries.bench.values.length) lines.push({ values: fseries.bench.values, color: '#5d6a85', width: 1.4, dash: '4 4' })
      }
      v.heroChartEl = this._chart('hero' + fk + per, lines, 184)
      v.heroLegend = [{ mark: '●', label: f.name, color: f.color }, { mark: '┄', label: f.benchShort, color: '#5d6a85' }]
      v.heroStats = [
        { l: 'Alpha', v: this._sign(f.alpha, 1) + '%', sub: 'vs ' + f.benchShort, c: '#21d07a', tooltip: 'Active return compared to the benchmark.' },
        { l: 'Beta', v: (f.beta || 0).toFixed(2), sub: '3Y daily', c: '#cdd6e8', tooltip: 'Measure of volatility relative to the market.' },
        { l: 'Sharpe', v: (f.sharpe || 0).toFixed(2), sub: 'risk-adj', c: '#cdd6e8', tooltip: 'Risk-adjusted return.' },
        { l: 'Volatility', v: (f.vol || 0).toFixed(1) + '%', sub: 'ann σ', c: '#cdd6e8', tooltip: 'Annualized standard deviation of returns.' },
        { l: 'Fwd P/E', v: (f.pe || 0).toFixed(1), sub: 'wtd avg', c: '#cdd6e8', tooltip: 'Forward Price-to-Earnings ratio.' },
        { l: 'Div Yield', v: (f.dy || 0).toFixed(1) + '%', sub: 'ttm', c: '#cdd6e8', tooltip: 'Dividend yield.' },
      ]
    }

    const dashSrc = fk === 'all' ? this.allH : this.allH.filter((h) => h.fund === fk)
    const dashSorted = dashSrc.slice().sort((a, b) => b.w - a.w)
    v.dashHoldings = dashSorted.slice(0, 10).map((h) => this._rowVM(h, 'dashboard'))
    v.dashTitle = fk === 'all' ? 'Top Holdings' : F[fk].name + ' Holdings'
    v.dashCount = dashSrc.length + ' positions'
    v.dashMoreText = 'View all ' + dashSrc.length + ' positions →'

    const fsec = this._fundSectors(fk).map((x) => ({ ...x, color: GROUP_COLOR[x.name] }))
    v.donutEl = this._donut(fsec)
    v.donutLegend = fsec.slice(0, 5).map((x) => ({ name: x.name, pct: x.pct.toFixed(0) + '%', color: x.color, on: () => this._openSector(x.name, 'dashboard') }))

    const contribs = dashSrc.map((h) => ({ t: h.t, c: (h.w / 100) * h.mtd })).sort((a, b) => b.c - a.c)
    const pick = contribs.slice(0, 3).concat(contribs.slice(-1))
    const maxAbs = Math.max.apply(null, pick.map((p) => Math.abs(p.c))) || 1
    v.contribTitle = 'Contributors · MTD'
    v.contribRows = pick.map((p) => ({ t: p.t, v: this._sign(p.c, 2), color: this._col(p.c), w: (Math.abs(p.c) / maxAbs * 100).toFixed(0) + '%', alignRight: p.c < 0 }))

    // stocks list
    const q = (st.query || '').toLowerCase()
    const stockPool = fk === 'all' ? this.allH : this.allH.filter((h) => h.fund === fk)
    let rows = stockPool.filter((h) => !q || h.t.toLowerCase().indexOf(q) >= 0 || h.n.toLowerCase().indexOf(q) >= 0 || (h.s || '').toLowerCase().indexOf(q) >= 0)
    const dir = st.sortDir === 'asc' ? 1 : -1
    const keyf = { t: (h) => h.t, n: (h) => h.n, s: (h) => h.s || '', w: (h) => h.w, mv: (h) => h.mv || 0, px: (h) => h.px, chg: (h) => h.chg, mtd: (h) => h.mtd, pe: (h) => h.pe || 0 }
    const kf = keyf[st.sortKey] || keyf.w
    rows = rows.slice().sort((a, b) => { const x = kf(a), y = kf(b); return typeof x === 'string' ? x.localeCompare(y) * dir : (x - y) * dir })
    v.stocksRows = rows.map((h) => this._rowVM(h, 'stocks'))
    v.stocksTitle = fk === 'all' ? 'All Holdings' : F[fk].name + ' Holdings'
    v.stocksCount = rows.length + ' of ' + stockPool.length + ' holdings · ' + (fk === 'all' ? 'both funds' : F[fk].name)
    v.query = st.query || ''
    const heads = [['t', 'Ticker', 'left'], ['n', 'Name', 'left'], ['s', 'Sector', 'left'], ['', 'Fund', 'right'], ['w', 'Wt', 'right'], ['mv', 'Mkt Val', 'right'], ['px', 'Price', 'right'], ['chg', 'Day', 'right'], ['mtd', 'MTD', 'right'], ['pe', 'P/E', 'right']]
    v.stocksHead = heads.map(([k, label, align]) => ({ label, align, color: (k && k === st.sortKey) ? '#cdd6e8' : '#6b7794', caret: (k && k === st.sortKey) ? (st.sortDir === 'asc' ? ' ↑' : ' ↓') : '', on: k ? () => this.setState((s2) => ({ sortKey: k, sortDir: (s2.sortKey === k && s2.sortDir === 'desc') ? 'asc' : 'desc' })) : () => {} }))

    // sectors kanban — one column per UOIG group, in taxonomy order
    const agg = this._aggSectors(fk)
    const singleFund = fk !== 'all'
    v.sectorCols = SECTOR_GROUPS.map((g) => {
      const a = agg[g.name]
      if (!a) return { name: g.name, color: g.color, members: g.members.join(' · '), shareStr: '0.0%', count: 0, cards: [], singleFund, on: () => {} }
      const gd = (a.wByFund[fundA] || 0) / 100 * F[fundA].aum, vd = (a.wByFund[fundB] || 0) / 100 * F[fundB].aum
      const tot = gd + vd || 1
      const cards = a.holdings.slice().sort((x, y) => y.w - x.w).map((h) => ({
        t: h.t, n: h.n, wStr: h.w.toFixed(1) + '%',
        dayStr: this._sign(h.chg) + '%', dayColor: this._col(h.chg),
        mtdStr: this._sign(h.mtd, 1) + '%', mtdColor: this._col(h.mtd),
        fundColor: (F[h.fund] || {}).color || '#5a93f9', fundTag: (F[h.fund] || {}).tag || h.fund,
        open: () => this._openStock(h.t, 'sectors'),
      }))
      return {
        name: g.name, color: g.color, members: g.members.join(' · '),
        shareStr: a.share.toFixed(1) + '%', count: a.count,
        retStr: this._sign(a.ret, 1) + '%', retColor: this._col(a.ret),
        gPct: (gd / tot * 100).toFixed(0) + '%', vPct: (vd / tot * 100).toFixed(0) + '%',
        cards, singleFund,
        on: () => this._openSector(g.name, 'sectors'),
      }
    })

    // stock detail — a portfolio holding (rich, DB-backed) or any equity looked
    // up live on Yahoo Finance (quote-backed). The page renders for both.
    if (st.view === 'stock') {
      const heldH = this.byT[st.ticker]
      const qstate = st.quotes[st.ticker]
      const quoteObj = (qstate && qstate !== 'loading' && qstate !== 'error') ? qstate : null
      v.stkLoading = !heldH && (qstate === 'loading' || qstate === undefined)
      v.stkErr = !heldH && qstate === 'error'
      const h = heldH || quoteObj
      if (h) {
        const held = !!heldH
        const f = held ? F[h.fund] : null
        const accent = f ? f.color : '#5a93f9'
        const sseries = st.series[`stk:${st.ticker}:${per}`]
        const mcStr = h.mc != null ? '$' + (h.mc >= 1000 ? (h.mc / 1000).toFixed(2) + 'T' : h.mc.toFixed(0) + 'B') : '—'
        const hasChg = h.chg != null
        const prevClose = hasChg ? h.px / (1 + h.chg / 100) : h.px
        const dayAbs = h.px - prevClose
        v.stk = {
          t: h.t, n: h.n, s: h.s || '—', industry: (held ? h.s : (h.industry || h.s)) || '—',
          held, fundLabel: held ? f.name : (h.exchange || 'Yahoo Finance'), fundColor: accent,
          benchShort: f ? f.benchShort : 'Live quote',
          pxStr: '$' + this._num(h.px),
          dayStr: hasChg ? this._sign(h.chg) + '%' : '—',
          dayAbs: hasChg ? '(' + this._sign(dayAbs, 2).replace('+', '+$').replace('-', '-$') + ')' : '',
          dayColor: hasChg ? this._col(h.chg) : '#9aa7c2', dayArrow: hasChg ? (h.chg >= 0 ? '▲' : '▼') : '',
          asof: held ? 'As of ' + String(st.data.asOf).slice(0, 10) : 'Live · Yahoo Finance',
          descr: h.desc || 'No company description available from Yahoo Finance.',
          loStr: h.lo != null ? '$' + h.lo : '—', hiStr: h.hi != null ? '$' + h.hi : '—',
          rangePos: (h.lo != null && h.hi != null) ? Math.max(0, Math.min(100, (h.px - h.lo) / ((h.hi - h.lo) || 1) * 100)).toFixed(0) + '%' : '50%',
        }
        const stkVals = (sseries && sseries.close) ? sseries.close : []
        const stkDates = (sseries && sseries.dates) ? sseries.dates : []
        v.stkChartEl = React.createElement(PriceChart, { key: 'stk' + h.t + per, dates: stkDates, values: stkVals, color: accent, height: 230 })
        v.stkChartLegend = [{ mark: '●', color: accent, label: h.t }]
        v.stkSnapshot = [
          { l: 'Market Cap', v: mcStr, size: '17px', tooltip: "Total market value of a company's outstanding shares." },
          { l: 'Fwd P/E', v: h.pe ? h.pe.toFixed(1) : '—', size: '17px', tooltip: 'Forward Price-to-Earnings ratio.' },
          { l: 'Price / Book', v: h.pb ? h.pb.toFixed(1) : '—', size: '17px', tooltip: 'Price-to-Book ratio.' },
          { l: 'EV / EBITDA', v: h.evEbitda != null ? h.evEbitda.toFixed(1) + 'x' : '—', size: '17px', tooltip: 'Enterprise Value to Earnings Before Interest, Taxes, Depreciation, and Amortization.' },
          { l: 'Div Yield', v: h.dy != null ? h.dy.toFixed(2) + '%' : '—', size: '17px', tooltip: 'Dividend yield.' },
          { l: 'Beta (3Y)', v: h.beta != null ? h.beta.toFixed(2) : '—', size: '17px', tooltip: '3-year daily beta.' },
          { l: '52W Range', v: (h.lo != null ? '$' + h.lo + '–' + h.hi : '—'), size: '14px', tooltip: '52-week low and high prices.' },
        ]
        v.stkFacts = held ? [
          { l: 'Sector', v: h.s || '—', color: '#cdd6e8' },
          { l: 'Fund', v: f.name, color: '#cdd6e8' },
          { l: 'Portfolio Weight', v: h.w.toFixed(1) + '%', color: '#cdd6e8' },
          { l: 'Beta (3Y)', v: h.beta != null ? h.beta.toFixed(2) : '—', color: '#cdd6e8' },
          { l: 'Day Change', v: this._sign(h.chg) + '%', color: this._col(h.chg) },
          { l: 'MTD Return', v: this._sign(h.mtd, 1) + '%', color: this._col(h.mtd) },
        ] : [
          { l: 'Sector', v: h.s || '—', color: '#cdd6e8' },
          { l: 'Industry', v: h.industry || '—', color: '#cdd6e8' },
          { l: 'Exchange', v: h.exchange || '—', color: '#cdd6e8' },
          { l: 'Beta', v: h.beta != null ? h.beta.toFixed(2) : '—', color: '#cdd6e8' },
          { l: 'Day Change', v: hasChg ? this._sign(h.chg) + '%' : '—', color: hasChg ? this._col(h.chg) : '#cdd6e8' },
          { l: 'Div Yield', v: h.dy != null ? h.dy.toFixed(2) + '%' : '—', color: '#cdd6e8' },
        ]
        const tabKey = st.stkTab || 'overview'
        v.stkTab = tabKey
        v.stkDetail = st.stkDetail[st.ticker]
        v.predDetail = st.predictions[st.ticker]
        v.thesisDetail = st.theses[st.ticker]
        v.stkTabs = [['overview', 'Overview'], ['thesis', 'Thesis'], ['financials', 'Financials'], ['earnings', 'Earnings'], ['news', 'News'], ['research', 'Research'], ['predictions', 'Predictions']]
          .filter(([k]) => held || (k !== 'thesis' && k !== 'predictions'))
          .map(([k, label]) => ({
            key: k, label, on: () => this.setState({ stkTab: k }),
            weight: k === tabKey ? 600 : 500, color: k === tabKey ? '#e8edf7' : '#6b7794',
            border: k === tabKey ? '2px solid #5a93f9' : '2px solid transparent',
          }))
        if (held) {
          const ctb = (h.w / 100) * h.mtd
          v.stkPos = { weightStr: h.w.toFixed(1) + '%', valueStr: this._kd(h.mv), sharesStr: (h.sh != null ? Math.round(h.sh).toLocaleString('en-US') : '—'), contribStr: this._sign(ctb, 2) + ' pp', contribColor: this._col(ctb) }
        } else {
          v.stkPos = null
        }
        // Top institutional shareholders (yfinance 13F).
        const hstate = st.holders[st.ticker]
        v.stkHoldersState = (hstate === 'loading' || hstate === undefined) ? 'loading' : (hstate === 'error' ? 'error' : 'ready')
        v.stkHolders = (v.stkHoldersState === 'ready') ? hstate.map((r) => ({
          holder: r.holder,
          pctStr: r.pct != null ? r.pct.toFixed(2) + '%' : '—',
          sharesStr: r.shares != null ? (r.shares >= 1e6 ? (r.shares / 1e6).toFixed(1) + 'M' : Math.round(r.shares).toLocaleString('en-US')) : '—',
          valueStr: r.value != null ? '$' + (r.value >= 1000 ? (r.value / 1000).toFixed(1) + 'B' : r.value.toFixed(0) + 'M') : '—',
        })) : []
        v.stkBackLabel = st.prevView === 'stocks' ? 'All Holdings' : (st.prevView === 'sector' ? (st.sector || 'Sector') : (st.prevView === 'coverage' ? 'My Coverage' : 'Dashboard'))
      }
    }

    // sector detail
    if (st.view === 'sector' && agg[st.sector]) {
      const a = agg[st.sector]
      const wTiles = []
      if (fk === 'all' || fk === fundA) wTiles.push({ label: F[fundA].name + ' Wt', color: '#5a93f9', val: (a.wByFund[fundA] || 0).toFixed(1) + '%' })
      if (fk === 'all' || fk === fundB) wTiles.push({ label: F[fundB].name + ' Wt', color: '#f4a531', val: (a.wByFund[fundB] || 0).toFixed(1) + '%' })
      v.sec = { name: a.name, shareStr: a.share.toFixed(1) + '%', count: a.count, ret: this._sign(a.ret, 1) + '%', retColor: this._col(a.ret), wTiles, color: a.color }
      v.secRows = a.holdings.slice().sort((x, y) => y.w - x.w).map((h) => this._rowVM(h, 'sector'))

      // Comparison chart (this sector vs iShares benchmarks) + weekly movers.
      const sper = st.sectorPeriod
      v.secPeriod = sper
      v.secPeriods = ['1M', '3M', '6M', 'YTD', '1Y', '5Y'].map((p) => ({ k: p, bg: p === sper ? '#13203a' : 'transparent', color: p === sper ? '#cdd6e8' : '#6b7794', weight: p === sper ? 600 : 500, on: () => this.setState({ sectorPeriod: p }) }))
      const ss = st.sectorSeries[`${st.sector}:${sper}`]
      v.secState = ss === 'loading' ? 'loading' : ss === 'error' ? 'error' : (ss ? 'ready' : 'loading')
      if (v.secState === 'ready') {
        const pal = ['#5a93f9', '#f4a531', '#8aa0c8', '#3fb6c0']
        const chartSeries = []
        if (ss.sector && ss.sector.values && ss.sector.values.length) chartSeries.push({ label: a.name, color: a.color, values: ss.sector.values, area: true })
        ss.benchmarks.forEach((b, i) => { if (b.values && b.values.length) chartSeries.push({ label: b.ticker, color: pal[i % pal.length], values: b.values }) })
        v.secChartEl = React.createElement(IndexChart, { key: 'sec' + st.sector + sper, dates: (ss.sector && ss.sector.dates) || [], series: chartSeries, height: 190 })
        v.secChartLegend = [{ mark: '●', color: a.color, label: a.name }]
          .concat(ss.benchmarks.map((b, i) => ({ mark: '┄', color: pal[i % pal.length], label: b.ticker })))
        v.secKpis = [{ label: a.name + ' · ' + sper, val: this._sign((ss.sector.ret || 0) * 100, 1) + '%', color: a.color, valColor: this._col(ss.sector.ret || 0), hero: true }]
          .concat(ss.benchmarks.map((b, i) => ({ label: b.ticker + ' · ' + b.name, val: this._sign((b.ret || 0) * 100, 1) + '%', color: pal[i % pal.length], valColor: '#cdd6e8' })))
        const mv = (m) => ({ t: m.t, n: m.n, pct: this._sign(m.ret * 100, 1) + '%', color: this._col(m.ret), on: () => this._openStock(m.t, 'sector') })
        v.secTop = ((ss.movers && ss.movers.top) || []).map(mv)
        v.secBottom = ((ss.movers && ss.movers.bottom) || []).map(mv)
      }
    }

    // claude dock
    let ctxLabel = 'Portfolio', ctxShort = 'the portfolio'
    if (st.view === 'stock' && v.stk) { const h = v.stk; ctxLabel = h.t + ' · ' + (h.n || '').slice(0, 16); ctxShort = h.t }
    else if (st.view === 'sector' && agg[st.sector]) { ctxLabel = 'Sector · ' + st.sector; ctxShort = st.sector }
    else { const lbl = fk === 'all' ? 'Combined' : F[fk].name; ctxLabel = lbl + ' · ' + per; ctxShort = 'this fund' }
    v.ctxLabel = ctxLabel; v.ctxShort = ctxShort
    v.chatEmpty = st.chat.length === 0 && !st.loading
    v.chatMsgs = st.chat.map((m, i) => { const user = m.role === 'user'; return { body: user ? m.content : this._fmt(m.content), align: user ? 'flex-end' : 'flex-start', maxw: user ? '86%' : '95%', bg: user ? '#13203a' : '#15112c', border: user ? '#13203a' : '#2a2350', radius: user ? '11px 11px 3px 11px' : '11px 11px 11px 3px', color: user ? '#cdd6e8' : '#d7d2f0', key: i } })
    v.loading = st.loading; v.input = st.input || ''
    v.sendBg = (st.input && st.input.trim() && !st.loading) ? '#5a4fd6' : '#2c2550'
    return v
  }
}
