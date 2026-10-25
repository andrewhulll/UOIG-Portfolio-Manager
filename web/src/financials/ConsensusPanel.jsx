import React, { useMemo, useState } from 'react'
import {
  fmtCompact, fmtPercent, fmtPrice, trackPos, upside, revisionChange, ACTION_LABEL, gradeText, targetText,
  RATING_KEYS, ratingLabel, ratingOrder, filterBroker, consensusLabel, buyShare,
} from './format.js'

const SHOWN = 10
const eps = (v) => (v == null ? '—' : v < 0 ? `(${Math.abs(v).toFixed(2)})` : v.toFixed(2))
const tone = (v) => (v == null || v === 'n/m' ? 'dim' : v < 0 ? 'neg' : v > 0 ? 'pos' : '')

function Card({ title, note, wide, half, children }) {
  return (
    <section className={`fin-card${wide ? ' fin-wide' : ''}${half ? ' fin-half' : ''}`}>
      <h3 className="fin-card-title">{title}</h3>
      {note ? <p className="fin-card-note">{note}</p> : null}
      {children}
    </section>
  )
}

// A low-high track with a tick for the mean: shows how skewed the range is around it.
function Range({ lo, hi, mark, label }) {
  const pos = trackPos(mark, lo, hi)
  return (
    <span className="fin-range" role="img" aria-label={label}>
      <span className="fin-range-track">{pos != null ? <span className="fin-range-mark" style={{ left: pos + '%' }} /> : null}</span>
    </span>
  )
}

function Estimates({ rows, cur }) {
  return (
    <Card wide title="Analyst estimates" note={cur ? `Consensus averages. EPS and revenue in ${cur}.` : 'Consensus averages.'}>
      <div className="fin-scroll" tabIndex={0} role="region" aria-label="Analyst estimates">
        <table className="fin-table fin-compact">
          <thead>
            <tr><th scope="col" className="fin-label-col">Period</th>
              <th scope="col">EPS</th><th scope="col">Range</th><th scope="col">vs year ago</th>
              <th scope="col">Revenue</th><th scope="col">Range</th><th scope="col">vs year ago</th><th scope="col">Analysts</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <th scope="row" className="fin-label-col">{r.period}</th>
                <td><strong>{eps(r.eps.avg)}</strong></td>
                <td className="fin-range-cell"><span className="fin-range-lo">{eps(r.eps.low)}</span>
                  <Range lo={r.eps.low} hi={r.eps.high} mark={r.eps.avg} label={`EPS estimates from ${eps(r.eps.low)} to ${eps(r.eps.high)}, mean ${eps(r.eps.avg)}`} />
                  <span className="fin-range-hi">{eps(r.eps.high)}</span></td>
                <td className={tone(r.eps.growth)}>{fmtPercent(r.eps.growth)}</td>
                <td><strong>{fmtCompact(r.revenue.avg)}</strong></td>
                <td className="fin-range-cell"><span className="fin-range-lo">{fmtCompact(r.revenue.low)}</span>
                  <Range lo={r.revenue.low} hi={r.revenue.high} mark={r.revenue.avg} label={`Revenue estimates from ${fmtCompact(r.revenue.low)} to ${fmtCompact(r.revenue.high)}`} />
                  <span className="fin-range-hi">{fmtCompact(r.revenue.high)}</span></td>
                <td className={tone(r.revenue.growth)}>{fmtPercent(r.revenue.growth)}</td>
                <td>{r.analysts ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function Revisions({ rows }) {
  return (
    <Card title="EPS estimate revisions" note="Consensus EPS now versus earlier. A rising estimate usually means analysts are getting more positive.">
      <div className="fin-scroll" tabIndex={0} role="region" aria-label="EPS revisions">
        <table className="fin-table fin-compact">
          <thead><tr><th scope="col" className="fin-label-col">Period</th><th scope="col">Now</th><th scope="col">7d ago</th><th scope="col">30d ago</th><th scope="col">60d ago</th><th scope="col">90d ago</th><th scope="col">90d change</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const ch = revisionChange(r)
              return (
                <tr key={r.key}>
                  <th scope="row" className="fin-label-col">{r.period}</th>
                  <td><strong>{eps(r.current)}</strong></td><td>{eps(r.d7)}</td><td>{eps(r.d30)}</td><td>{eps(r.d60)}</td><td>{eps(r.d90)}</td>
                  <td className={tone(ch)}>{fmtPercent(ch)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function Surprises({ rows }) {
  const worst = Math.max(0.01, ...rows.map((r) => Math.abs(r.surprisePct || 0)))
  return (
    <Card title="Earnings surprises" note="Reported EPS against what analysts expected.">
      <div className="fin-scroll" tabIndex={0} role="region" aria-label="Earnings surprises">
        <table className="fin-table fin-compact">
          <thead><tr><th scope="col" className="fin-label-col">Quarter</th><th scope="col">Actual</th><th scope="col">Estimate</th><th scope="col">Surprise</th><th scope="col"><span className="fin-sr">Surprise chart</span></th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const w = Math.min(100, (Math.abs(r.surprisePct || 0) / worst) * 100) / 2
              return (
                <tr key={r.end}>
                  <th scope="row" className="fin-label-col">{r.period}</th>
                  <td><strong>{eps(r.actual)}</strong></td><td>{eps(r.estimate)}</td>
                  <td className={tone(r.surprisePct)}>{fmtPercent(r.surprisePct)}</td>
                  <td className="fin-diverge" aria-hidden="true">
                    <span className="fin-diverge-axis" />
                    {r.surprisePct != null ? <span className={`fin-diverge-bar ${r.surprisePct < 0 ? 'neg' : 'pos'}`}
                      style={r.surprisePct < 0 ? { right: '50%', width: w + '%' } : { left: '50%', width: w + '%' }} /> : null}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function Targets({ t, cur }) {
  const lo = t.low, hi = t.high
  const up = upside(t.mean, t.current)
  const pos = (v) => trackPos(v, lo, hi)
  return (
    <Card half title="Price targets" note={cur ? `In ${cur}, the currency the stock trades in.` : undefined}>
      <div className="fin-target">
        <div className="fin-target-head">
          <div><div className="fin-big">{fmtPrice(t.mean)}</div><div className="fin-sub">Mean target</div></div>
          <div className={`fin-up ${tone(up)}`}>{up == null ? '—' : fmtPercent(up)}<span className="fin-sub"> vs current {fmtPrice(t.current)}</span></div>
        </div>
        <div className="fin-target-track" role="img" aria-label={`Price targets from ${fmtPrice(lo)} to ${fmtPrice(hi)}, mean ${fmtPrice(t.mean)}, current price ${fmtPrice(t.current)}`}>
          <span className="fin-target-line" />
          {pos(t.median) != null ? <span className="fin-tick fin-tick-median" style={{ left: pos(t.median) + '%' }} /> : null}
          {pos(t.mean) != null ? <span className="fin-tick fin-tick-mean" style={{ left: pos(t.mean) + '%' }} /> : null}
          {pos(t.current) != null ? <span className="fin-tick fin-tick-now" style={{ left: pos(t.current) + '%' }} /> : null}
        </div>
        <div className="fin-target-scale"><span>Low {fmtPrice(lo)}</span><span>High {fmtPrice(hi)}</span></div>
        <div className="fin-legend">
          <span><i className="fin-dot fin-tick-now" />Current</span>
          <span><i className="fin-dot fin-tick-mean" />Mean</span>
          <span><i className="fin-dot fin-tick-median" />Median {fmtPrice(t.median)}</span>
        </div>
        {t.current != null && (t.current < lo || t.current > hi) ? <p className="fin-card-note">The current price is outside the range of analyst targets.</p> : null}
      </div>
    </Card>
  )
}

function Ratings({ rows }) {
  const ordered = ratingOrder(rows)
  const now = rows[0]
  const label = consensusLabel(now)
  const share = buyShare(now)
  return (
    <Card half title="Analyst ratings" note="How many analysts rate it each way, month by month.">
      {label ? (
        <div className="fin-verdict">
          <div className="fin-big">{label}</div>
          <div className="fin-sub">{now.total} analysts{share != null ? `, ${Math.round(share * 100)}% rate it buy or better` : ''}</div>
        </div>
      ) : null}
      <div className="fin-ratings">
        {ordered.map((r) => (
          <div className="fin-rating-row" key={r.period}>
            <span className="fin-rating-label">{ratingLabel(r.period)}</span>
            <span className="fin-rating-bar" role="img" aria-label={RATING_KEYS.map(([k, l]) => `${r[k]} ${l.toLowerCase()}`).join(', ')}>
              {RATING_KEYS.map(([k, , color]) => (r[k] ? <span key={k} style={{ width: (r[k] / r.total) * 100 + '%', background: color }} title={`${r[k]}`}>{r[k] / r.total >= 0.09 ? r[k] : ''}</span> : null))}
            </span>
            <span className="fin-rating-total">{r.total}</span>
          </div>
        ))}
        <div className="fin-legend">{RATING_KEYS.map(([k, l, c]) => <span key={k}><i className="fin-dot" style={{ background: c }} />{l}</span>)}</div>
      </div>
    </Card>
  )
}

function Growth({ rows }) {
  const diff = (r) => (r.stock == null || r.index == null ? null : r.stock - r.index)
  return (
    <Card wide title="Expected growth" note="Estimated earnings growth for the stock against its index. A positive gap means analysts expect it to grow faster than the market.">
      <div className="fin-scroll" tabIndex={0} role="region" aria-label="Growth estimates">
        <table className="fin-table fin-compact fin-growth">
          <thead><tr><th scope="col" className="fin-label-col"><span className="fin-sr">Measure</span></th>{rows.map((r) => <th scope="col" key={r.key}>{r.period}</th>)}</tr></thead>
          <tbody>
            <tr><th scope="row" className="fin-label-col">Stock</th>{rows.map((r) => <td key={r.key} className={tone(r.stock)}>{fmtPercent(r.stock)}</td>)}</tr>
            <tr><th scope="row" className="fin-label-col">Index</th>{rows.map((r) => <td key={r.key} className="dim">{fmtPercent(r.index)}</td>)}</tr>
            <tr><th scope="row" className="fin-label-col">Gap</th>{rows.map((r) => { const d = diff(r); return <td key={r.key} className={tone(d)}>{d == null ? '—' : (d > 0 ? '+' : '') + fmtPercent(d)}</td> })}</tr>
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function BrokerLog({ log }) {
  const [firm, setFirm] = useState('')
  const [action, setAction] = useState('all')
  const [limit, setLimit] = useState(SHOWN)
  const actions = useMemo(() => [...new Set(log.map((r) => r.action).filter(Boolean))], [log])
  const rows = useMemo(() => filterBroker(log, { firm, action }), [log, firm, action])
  return (
    <Card wide title="Broker actions" note={`The latest ${log.length} rating and price-target changes reported to Yahoo. This is a log of what analysts did, not their models.`}>
      <div className="fin-filters">
        <label><span className="fin-sr">Filter by firm</span>
          <input type="search" placeholder="Filter by firm" value={firm} onChange={(e) => { setFirm(e.target.value); setLimit(SHOWN) }} /></label>
        <label><span className="fin-sr">Filter by action</span>
          <select value={action} onChange={(e) => { setAction(e.target.value); setLimit(SHOWN) }}>
            <option value="all">All actions</option>
            {actions.map((a) => <option key={a} value={a}>{ACTION_LABEL[a] || a}</option>)}
          </select></label>
        <span className="fin-note">{rows.length} of {log.length}</span>
      </div>
      {rows.length === 0 ? <p className="fin-card-note">No broker actions match that filter.</p> : (
        <div className="fin-scroll" tabIndex={0} role="region" aria-label="Broker actions">
          <table className="fin-table fin-compact fin-log">
            <thead><tr><th scope="col" className="fin-label-col">Firm</th><th scope="col">Date</th><th scope="col">Action</th><th scope="col">Rating</th><th scope="col">Price target</th></tr></thead>
            <tbody>
              {rows.slice(0, limit).map((r, i) => (
                <tr key={i}>
                  <th scope="row" className="fin-label-col">{r.firm || '—'}</th>
                  <td>{r.date}</td>
                  <td className={r.action === 'up' ? 'pos' : r.action === 'down' ? 'neg' : ''}>{ACTION_LABEL[r.action] || r.action || '—'}</td>
                  <td>{gradeText(r)}</td>
                  <td className={r.targetAction === 'Raises' ? 'pos' : r.targetAction === 'Lowers' ? 'neg' : ''}>{targetText(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > limit ? <button type="button" className="fin-btn fin-btn-quiet fin-more" onClick={() => setLimit(limit + SHOWN)}>Show {Math.min(SHOWN, rows.length - limit)} more</button> : null}
    </Card>
  )
}

export function ConsensusPanel({ consensus, currency }) {
  if (!consensus) {
    return (
      <section className="fin-panel fin-research" aria-label="Analyst consensus">
        <h2 className="fin-title">Analyst consensus</h2>
        <div className="fin-notice"><div className="fin-notice-title">No analyst coverage found</div>
          <div className="fin-notice-body">Yahoo Finance has no estimates, price targets or broker actions for this security.</div></div>
      </section>
    )
  }
  const c = consensus
  return (
    <section className="fin-panel fin-research" aria-label="Analyst consensus">
      <h2 className="fin-title">Analyst consensus<span className="fin-src"> · earnings_estimate, revenue_estimate, analyst_price_targets, upgrades_downgrades</span></h2>
      <p className="fin-card-note fin-intro">Yahoo publishes consensus summaries, not the analysts' own models. Line-item forecasts would need a data service such as CapIQ or FactSet.</p>
      <div className="fin-grid">
        {c.targets ? <Targets t={c.targets} cur={currency && currency.trading} /> : null}
        {c.ratingTrend && c.ratingTrend.length ? <Ratings rows={c.ratingTrend} /> : null}
        {c.estimates && c.estimates.length ? <Estimates rows={c.estimates} cur={currency && currency.reporting} /> : null}
        {c.revisions && c.revisions.length ? <Revisions rows={c.revisions} /> : null}
        {c.surprises && c.surprises.length ? <Surprises rows={c.surprises} /> : null}
        {c.growth && c.growth.length ? <Growth rows={c.growth} /> : null}
        {c.brokerLog && c.brokerLog.length ? <BrokerLog log={c.brokerLog} /> : null}
      </div>
    </section>
  )
}
