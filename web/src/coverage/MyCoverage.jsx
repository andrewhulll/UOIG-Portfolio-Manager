import React from 'react'
import { getMyCoverage } from '../api.js'
import { s } from '../ui.js'

const SECTOR_COLORS = { TMT: '#5a93f9', Consumer: '#e8674c', Financials: '#c06fd6', Financial: '#c06fd6', Healthcare: '#21d07a', IME: '#f4a531' }

function sign(v, dp = 1) { return (v >= 0 ? '+' : '') + v.toFixed(dp) + '%' }
function chgColor(v) { return v == null ? '#6b7794' : (v >= 0 ? '#21d07a' : '#ff5666') }

function EarningsBanner({ tickers }) {
  if (!tickers.length) return null
  return (
    <div style={s('display:flex;align-items:center;gap:10px;background:#2a1f0c;border:1px solid #4a3a1d;border-radius:8px;padding:11px 16px;margin-bottom:16px;')}>
      <span style={s("font:600 10px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;color:#f4a531;")}>Earnings this week</span>
      <span style={s("font:500 12px 'IBM Plex Sans';color:#e8edf7;")}>{tickers.join(', ')} report{tickers.length === 1 ? 's' : ''} within 5 days</span>
    </div>
  )
}

function CoverageCard({ card, onOpenStock }) {
  const soon = card.earningsInDays != null && card.earningsInDays >= 0 && card.earningsInDays <= 5
  const sectorColor = SECTOR_COLORS[card.sector] || '#6b7794'
  return (
    <div onClick={() => onOpenStock(card.ticker)} style={s('background:#111a2e;border:1px solid #1d2840;border-radius:10px;padding:16px 18px;cursor:pointer;transition:border-color .15s;')}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = '#2a3a5c' }} onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#1d2840' }}>
      <div style={s('display:flex;align-items:flex-start;justify-content:space-between;gap:10px;')}>
        <div>
          <div style={s('display:flex;align-items:center;gap:8px;')}>
            <span style={s("font:700 15px 'IBM Plex Mono';color:#e8edf7;")}>{card.ticker}</span>
            {card.sector && <span style={{ ...s("font:600 9px 'IBM Plex Sans';border-radius:4px;padding:2px 7px;"), color: sectorColor, background: sectorColor + '18', border: '1px solid ' + sectorColor + '40' }}>{card.sector}</span>}
          </div>
          <div style={s("font:500 11px 'IBM Plex Sans';color:#7e8aa6;margin-top:2px;")}>{card.name}</div>
        </div>
        <div style={s('text-align:right;')}>
          <div style={s("font:600 15px 'IBM Plex Mono';color:#e8edf7;")}>{card.price != null ? '$' + card.price.toFixed(2) : '—'}</div>
          <div style={s("font:500 11px 'IBM Plex Mono';margin-top:2px;")}>
            <span style={{ color: chgColor(card.dayChangePct) }}>{card.dayChangePct != null ? sign(card.dayChangePct) : '—'}</span>
            <span style={s('color:#3c465e;margin:0 5px;')}>·</span>
            <span style={{ color: chgColor(card.mtdChangePct) }}>MTD {card.mtdChangePct != null ? sign(card.mtdChangePct) : '—'}</span>
          </div>
        </div>
      </div>

      <div style={{ ...s("display:flex;align-items:center;gap:8px;margin-top:12px;padding-top:12px;border-top:1px solid #1a2438;font:500 11px 'IBM Plex Sans';"), color: soon ? '#f4a531' : '#7e8aa6' }}>
        <span>Next earnings:</span>
        <span style={s("font-family:'IBM Plex Mono';")}>{card.nextEarnings || '—'}</span>
        {card.earningsInDays != null && card.earningsInDays >= 0 && (
          <span style={{ ...s("margin-left:auto;font:600 9px 'IBM Plex Sans';border-radius:4px;padding:2px 7px;"), color: soon ? '#f4a531' : '#6b7794', background: soon ? '#3a2c0f' : '#161f34' }}>
            in {card.earningsInDays} day{card.earningsInDays === 1 ? '' : 's'}
          </span>
        )}
      </div>

      {card.news.length > 0 && (
        <div style={s('margin-top:12px;display:flex;flex-direction:column;gap:7px;')}>
          {card.news.map((n, i) => (
            <a key={i} href={n.link} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
              style={s("display:block;font:500 11.5px 'IBM Plex Sans';color:#cdd6e8;text-decoration:none;line-height:1.4;")}>
              {n.title}
              <span style={s("display:block;font:500 10px 'IBM Plex Sans';color:#5d6a85;margin-top:1px;")}>{n.publisher} · {n.ago}</span>
            </a>
          ))}
        </div>
      )}
      {!card.news.length && <div style={s("margin-top:12px;font:500 11px 'IBM Plex Sans';color:#5d6a85;")}>No recent headlines</div>}
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
    <div style={s('padding:28px 32px;max-width:1100px;')}>
      <div style={s('display:flex;align-items:baseline;justify-content:space-between;margin-bottom:18px;')}>
        <div>
          <div style={s("font:600 9px 'IBM Plex Sans';letter-spacing:.1em;text-transform:uppercase;color:#5a93f9;")}>Home</div>
          <h1 style={s("font:600 20px 'IBM Plex Sans';color:#e8edf7;margin:4px 0 0;")}>My Coverage</h1>
        </div>
        <span style={s("font:500 11px 'IBM Plex Sans';color:#7e8aa6;")}>{data.tickers.length} name{data.tickers.length === 1 ? '' : 's'}</span>
      </div>
      <EarningsBanner tickers={data.earningsThisWeek} />
      <div style={s('display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;')}>
        {data.tickers.map((card) => <CoverageCard key={card.ticker} card={card} onOpenStock={onOpenStock} />)}
      </div>
    </div>
  )
}
