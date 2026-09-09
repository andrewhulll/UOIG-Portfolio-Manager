import React from 'react'
import { getMyCoverage } from '../api.js'
import { s, SECTOR_COLORS } from '../ui.js'
import { smoothPath } from '../charts/PriceChart.jsx'

const RATING_COLORS = { 'Strong Buy': '#21d07a', Buy: '#21d07a', Hold: '#f4a531', Sell: '#ff5666', 'Strong Sell': '#ff5666' }

function sign(v, dp = 1) { return (v >= 0 ? '+' : '') + v.toFixed(dp) + '%' }
function chgColor(v) { return v == null ? '#6b7794' : (v >= 0 ? '#21d07a' : '#ff5666') }
function fmtMc(mc) { return mc == null ? '—' : '$' + (mc >= 1000 ? (mc / 1000).toFixed(2) + 'T' : mc.toFixed(2) + 'B') }
function fmtPe(pe) { return pe == null ? '—' : pe.toFixed(1) + 'x' }

function EarningsBanner({ tickers }) {
  if (!tickers.length) return null
  return (
    <div style={s('display:flex;align-items:center;gap:10px;background:#2a1f0c;border:1px solid #4a3a1d;border-radius:8px;padding:11px 16px;margin-bottom:16px;')}>
      <span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;color:#f4a531;")}>Earnings this week</span>
      <span style={s("font:500 12px 'IBM Plex Sans';color:#e8edf7;")}>{tickers.join(', ')} report{tickers.length === 1 ? 's' : ''} within 5 days</span>
    </div>
  )
}

// Compact 1M price line — same Catmull-Rom smoothing as the stock page's chart,
// scaled down to fit a card header with no axis or hover state.
function Spark({ values, height }) {
  if (!values || values.length < 2) {
    return <div style={s(`height:${height}px;display:flex;align-items:center;`)}><span style={s("font:500 10px 'IBM Plex Sans';color:#3c465e;")}>Not enough price history yet</span></div>
  }
  const W = 300, pad = 3
  const min = Math.min.apply(null, values), max = Math.max.apply(null, values)
  const span = (max - min) || 1
  const color = values[values.length - 1] >= values[0] ? '#21d07a' : '#ff5666'
  const X = (i) => +((i / (values.length - 1)) * W).toFixed(2)
  const Y = (v) => +(height - pad - ((v - min) / span) * (height - pad * 2)).toFixed(2)
  const line = smoothPath(values.map((v, i) => [X(i), Y(v)]))
  const area = line + ' L' + W + ',' + height + ' L0,' + height + ' Z'
  const gid = 'cvg-spark-' + color.replace('#', '')
  return (
    <svg viewBox={'0 0 ' + W + ' ' + height} preserveAspectRatio="none" style={{ width: '100%', height: height + 'px', display: 'block' }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: color, stopOpacity: 0.22 }} />
          <stop offset="1" style={{ stopColor: color, stopOpacity: 0 }} />
        </linearGradient>
      </defs>
      <path d={area} style={{ fill: 'url(#' + gid + ')', stroke: 'none' }} />
      <path d={line} style={{ fill: 'none', stroke: color, strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round' }} />
    </svg>
  )
}

function Stat({ label, children }) {
  return (
    <div style={s('flex:1 1 110px;min-width:96px;')}>
      <div style={s("font:600 9px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#5d6a85;margin-bottom:5px;")}>{label}</div>
      {children}
    </div>
  )
}

function CoverageCard({ card, onOpenStock }) {
  const soon = card.earningsInDays != null && card.earningsInDays >= 0 && card.earningsInDays <= 5
  const sectorColor = SECTOR_COLORS[card.sector] || '#6b7794'
  const c = card.consensus
  const upside = (c && c.mean != null && card.price) ? (c.mean / card.price - 1) * 100 : null
  const ratingColor = c ? (RATING_COLORS[c.label] || '#7e8aa6') : '#7e8aa6'
  const points = card.thesis && card.thesis.points && card.thesis.points.length ? card.thesis.points : null

  return (
    <div onClick={() => onOpenStock(card.ticker)} style={s('background:#111a2e;border:1px solid #1d2840;border-radius:10px;padding:18px 20px;cursor:pointer;transition:border-color .15s;')}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = '#2a3a5c' }} onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#1d2840' }}>

      <div style={s('display:flex;align-items:flex-start;justify-content:space-between;gap:10px;')}>
        <div>
          <div style={s('display:flex;align-items:center;gap:7px;')}>
            <span style={s("font:700 16px 'IBM Plex Mono';color:#e8edf7;")}>{card.ticker}</span>
            <span style={{ ...s("font:600 8px 'IBM Plex Sans';letter-spacing:.05em;text-transform:uppercase;border-radius:4px;padding:2px 6px;"), color: card.held ? '#5a93f9' : '#6b7794', border: '1px solid ' + (card.held ? '#28406e' : '#1d2840') }}>{card.held ? 'Position' : 'Coverage only'}</span>
            {card.sector && <span style={{ ...s("font:600 9px 'IBM Plex Sans';border-radius:4px;padding:2px 7px;"), color: sectorColor, background: sectorColor + '18', border: '1px solid ' + sectorColor + '40' }}>{card.sector}</span>}
          </div>
          <div style={s("font:500 11px 'IBM Plex Sans';color:#7e8aa6;margin-top:3px;")}>{card.name}</div>
        </div>
        <div style={s('text-align:right;')}>
          <div style={s("font:600 16px 'IBM Plex Mono';color:#e8edf7;")}>{card.price != null ? '$' + card.price.toFixed(2) : '—'}</div>
          <div style={s("font:500 11px 'IBM Plex Mono';margin-top:2px;")}>
            <span style={{ color: chgColor(card.dayChangePct) }}>{card.dayChangePct != null ? sign(card.dayChangePct) : '—'}</span>
            <span style={s('color:#3c465e;margin:0 5px;')}>·</span>
            <span style={{ color: chgColor(card.mtdChangePct) }}>MTD {card.mtdChangePct != null ? sign(card.mtdChangePct) : '—'}</span>
          </div>
        </div>
      </div>

      <div style={s('margin-top:12px;')}><Spark values={card.series} height={44} /></div>

      <div style={s('display:flex;flex-wrap:wrap;gap:14px 20px;margin-top:14px;padding-top:14px;border-top:1px solid #1a2438;')}>
        <Stat label="Next earnings">
          <div style={s("font:500 12px 'IBM Plex Mono';color:" + (soon ? '#f4a531' : '#cdd6e8') + ';')}>{card.nextEarnings ? (card.nextEarningsEstimated ? '~' : '') + card.nextEarnings : '—'}</div>
          {soon && <div style={s("font:600 9px 'IBM Plex Sans';color:#f4a531;margin-top:2px;")}>in {card.earningsInDays}d</div>}
        </Stat>
        <Stat label="Street">
          {c ? (
            <>
              <div style={s("font:600 12px 'IBM Plex Sans';")}><span style={{ color: ratingColor }}>{c.label}</span></div>
              {upside != null && <div style={{ ...s("font:500 10.5px 'IBM Plex Mono';margin-top:2px;"), color: chgColor(upside) }}>{sign(upside, 0)} to ${c.mean.toFixed(0)}</div>}
            </>
          ) : <div style={s("font:500 12px 'IBM Plex Sans';color:#3c465e;")}>No coverage</div>}
        </Stat>
        <Stat label="Mkt cap"><div style={s("font:500 12px 'IBM Plex Mono';color:#cdd6e8;")}>{fmtMc(card.marketCap)}</div></Stat>
        <Stat label="Fwd P/E"><div style={s("font:500 12px 'IBM Plex Mono';color:#cdd6e8;")}>{fmtPe(card.forwardPE)}</div></Stat>
      </div>

      <div style={s('margin-top:14px;padding-top:14px;border-top:1px solid #1a2438;')}>
        <div style={s('display:flex;align-items:baseline;justify-content:space-between;margin-bottom:10px;')}>
          <span style={s("font:600 9px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#5d6a85;")}>Thesis</span>
          {points && <span style={s("font-family:'IBM Plex Mono';font-size:9.5px;color:#3c465e;")}>{card.thesis.date}{card.thesis.analyst ? ' · ' + card.thesis.analyst : ''}</span>}
        </div>
        {points ? (
          <div style={s('display:flex;flex-direction:column;gap:7px;')}>
            {points.map((p, i) => (
              <div key={i} style={s('display:flex;gap:10px;align-items:flex-start;')}>
                <span style={s("width:16px;height:16px;flex:0 0 auto;margin-top:1px;border-radius:5px;background:#13203a;color:#5a93f9;display:flex;align-items:center;justify-content:center;font:600 9px 'IBM Plex Mono';")}>{i + 1}</span>
                <span style={s("font:400 12px/1.5 'IBM Plex Sans';color:#cdd6e8;")}>{p}</span>
              </div>
            ))}
          </div>
        ) : <div style={s("font:500 11.5px 'IBM Plex Sans';color:#5d6a85;")}>No thesis on file yet — add three points in THESIS.md.</div>}
      </div>

      {card.news.length > 0 && (
        <div style={s('margin-top:14px;padding-top:14px;border-top:1px solid #1a2438;display:flex;flex-direction:column;gap:8px;')}>
          <span style={s("font:600 9px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#5d6a85;")}>Headlines</span>
          {card.news.slice(0, 3).map((n, i) => (
            <a key={i} href={n.link} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
              style={s("display:block;font:500 11.5px 'IBM Plex Sans';color:#cdd6e8;text-decoration:none;line-height:1.4;")}>
              {n.title}
              <span style={s("display:block;font:500 10px 'IBM Plex Sans';color:#5d6a85;margin-top:1px;")}>{n.publisher} · {n.ago}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

export function MyCoverage({ onOpenStock }) {
  const [data, setData] = React.useState(null)
  const [error, setError] = React.useState('')
  const load = React.useCallback(() => {
    setError('')
    getMyCoverage().then(setData).catch((e) => setError(e.detail || 'Could not load coverage'))
  }, [])
  React.useEffect(() => { load() }, [load])

  if (error) {
    return (
      <div style={s('padding:40px;')}>
        <div style={s('background:#111a2e;border:1px solid #1d2840;border-radius:10px;padding:24px;text-align:center;')}>
          <div style={s("font:600 13px 'IBM Plex Sans';color:#e8edf7;margin-bottom:6px;")}>Coverage unavailable</div>
          <div style={s("font:500 12px 'IBM Plex Sans';color:#7e8aa6;margin-bottom:14px;")}>{error}</div>
          <button onClick={load} style={s("font:600 11px 'IBM Plex Sans';color:#5a93f9;background:#13203a;border:1px solid #28406e;border-radius:6px;padding:7px 16px;cursor:pointer;")}>Try again</button>
        </div>
      </div>
    )
  }
  if (!data) {
    return (
      <div style={s("padding:40px;font:500 12px 'IBM Plex Sans';color:#7e8aa6;display:flex;align-items:center;gap:8px;")}>
        <span className="settings-spinner" />Loading your coverage…
      </div>
    )
  }
  if (!data.tickers.length) {
    return (
      <div style={s('padding:40px;')}>
        <div style={s('background:#111a2e;border:1px solid #1d2840;border-radius:10px;padding:24px;text-align:center;')}>
          <div style={s("font:600 13px 'IBM Plex Sans';color:#e8edf7;margin-bottom:6px;")}>No coverage assigned yet</div>
          <div style={s("font:500 12px 'IBM Plex Sans';color:#7e8aa6;")}>Your sector lead assigns company coverage in the member directory.</div>
        </div>
      </div>
    )
  }
  return (
    <div style={s('padding:28px 32px;max-width:1280px;')}>
      <div style={s('display:flex;align-items:baseline;justify-content:space-between;margin-bottom:18px;')}>
        <div>
          <div style={s("font:600 9px 'IBM Plex Sans';letter-spacing:.1em;text-transform:uppercase;color:#5a93f9;")}>Home</div>
          <h1 style={s("font:600 20px 'IBM Plex Sans';color:#e8edf7;margin:4px 0 0;")}>My Coverage</h1>
        </div>
        <span style={s("font:500 11px 'IBM Plex Sans';color:#7e8aa6;")}>{data.tickers.length} name{data.tickers.length === 1 ? '' : 's'}</span>
      </div>
      <EarningsBanner tickers={data.earningsThisWeek} />
      <div style={s('display:grid;grid-template-columns:repeat(auto-fill,minmax(460px,1fr));gap:18px;align-items:start;')}>
        {data.tickers.map((card) => <CoverageCard key={card.ticker} card={card} onOpenStock={onOpenStock} />)}
      </div>
    </div>
  )
}
