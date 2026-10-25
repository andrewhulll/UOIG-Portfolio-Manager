import React from 'react'
import { getOrganizationMembers } from '../api.js'
import './tour.css'

const CHECK = <svg viewBox="0 0 16 16"><path d="m3 8.5 3 3 7-7.5" /></svg>
const pts = (items) => <ul className="wt-list">{items.map((t, i) => <li key={i}>{CHECK}<span>{t}</span></li>)}</ul>

// Each tab step: the live app is switched to `view`, and `target` (the rail item's title) is spotlighted.
function buildSteps(role) {
  const leader = role === 'sector-leader'
  const analyst = ['member', 'analyst', 'admin'].includes(role)
  const steps = [{ id: 'welcome', kind: 'welcome' }]
  if (analyst) steps.push({
    id: 'coverage', view: 'coverage', target: 'My Coverage', label: 'My Coverage', best: 'Start here',
    lede: 'The companies you are responsible for, in one place.',
    pts: ['Flag a news item on any company you cover and add a note on why it matters.', 'Your weekly digest builds itself from the items you flag.', 'It is due Thursday at 5:00 pm Pacific. Sector leaders read it the same evening.'],
    tip: <><b>Flag as you read.</b> Ten flags spread over the week beat a rushed Thursday afternoon.</>,
  })
  steps.push(leader ? {
    id: 'inbox', view: 'inbox', target: 'Inbox', label: 'Inbox', best: 'Start here',
    lede: 'Where your analysts’ weekly digests arrive.',
    pts: ['Digests from the analysts in your sector land here after Thursday’s deadline.', 'Acknowledge a digest to tell the analyst you have read it, and comment on single items.', 'The unread count shows on the tab.'],
    tip: <><b>Check it Thursday evening.</b> Analysts are waiting on your acknowledgement.</>,
  } : {
    id: 'inbox', view: 'inbox', target: 'Inbox', label: 'Inbox',
    lede: 'Where feedback on your digest comes back to you.',
    pts: ['Your sector leader acknowledges the digest here, and can leave comments on single items.', 'The unread count shows on the tab so you notice replies.'],
    tip: <><b>Check it Friday.</b> That is when most acknowledgements and questions arrive.</>,
  })
  steps.push(
    { id: 'funds', view: 'dashboard', target: 'Funds', extra: ['.app-fund-tabs'], label: 'Funds', lede: 'How Tall Firs and Alumni Fund are doing today.',
      pts: ['Switch between All Funds, Tall Firs and Alumni Fund in the top bar.', 'Pick a period from 1M to 5Y and the chart redraws.', 'Each fund is drawn against its benchmark: the Russell 3000 for Tall Firs, the Russell 2000 for Alumni Fund.'],
      tip: <><b>Look at the gap, not the number.</b> Analysts are judged on return compared with the benchmark.</> },
    { id: 'stocks', view: 'stocks', target: 'Stocks', extra: ['input[placeholder^="Search"]'], label: 'Stocks', best: 'Use often', lede: 'Every holding, with its own page.',
      pts: ['Click a ticker to open Overview, Thesis, Financials, Earnings, News, Research and Predictions.', 'Thesis and Predictions appear for companies the funds hold.', 'The search box at the top opens any listed company, held or not.'],
      tip: <><b>Start a pitch here.</b> The Thesis tab shows why we bought it and what we said would change our mind.</> },
    { id: 'sectors', view: 'sectors', target: 'Sectors', label: 'Sectors', lede: 'The five sector teams, side by side.',
      pts: ['TMT, Healthcare, Financial, IME and Consumer, each with its weight in the fund and in the index.', 'Open a sector to compare it with its sector ETFs.'],
      tip: <><b>Know your sector’s tilt.</b> It is the first thing a sector leader will ask about.</> },
  )
  if (analyst) steps.push({ id: 'optimize', view: 'optimize', target: 'Optimize', label: 'Optimize', lede: 'Test a change before anyone makes it.',
    pts: ['Diagnostics shows how far each fund strays from its benchmark and where the risk comes from.', 'What-if lets you try a trade and see the effect straight away.', 'The optimizer suggests weights. It never changes real holdings.'],
    tip: <><b>Use What-if when you pitch.</b> Showing the effect of your idea makes it easier to approve.</> })
  steps.push(
    { id: 'screener', view: 'screener', target: 'Screener', label: 'Screener', lede: 'Find companies we do not own yet.',
      pts: ['Filter by sector, size and valuation.', 'Open any result as a full stock page, with the same tabs as a holding.'],
      tip: <><b>Good for idea generation.</b> Filter to your sector and read the top three.</> },
    { id: 'assistant', view: 'assistant', target: 'Assistant', label: 'Assistant', best: 'Use often', lede: 'Ask Claude about the portfolio in plain English.',
      pts: ['It knows our holdings, the benchmark weights and recent news.', 'Ask for a summary of the week on your names, or why a fund moved today.', 'Open it from this tab, or from the ✦ button at the bottom right of every other page.'],
      tip: <><b>Try:</b> “What changed for my companies this week?” It is a quick way to start a Monday.</> },
    { id: 'week', kind: 'week' },
    { id: 'done', kind: 'done' },
  )
  return steps
}
const BEST = new Set(['My Coverage', 'Stocks', 'Assistant'])
const ROLE_NAME = { member: 'Analyst', analyst: 'Analyst', 'sector-leader': 'Sector Leader', admin: 'Admin' }

export function WelcomeTour({ auth, onNavigate, onClose }) {
  const role = auth.role
  const analyst = ['member', 'analyst', 'admin'].includes(role)
  const leader = role === 'sector-leader'
  const steps = React.useMemo(() => buildSteps(role), [role])
  const [i, setI] = React.useState(0)
  const [me, setMe] = React.useState(null)
  const [rects, setRects] = React.useState([])  // [{ box, extra }]
  const [pips, setPips] = React.useState([])
  const cardRef = React.useRef(null)
  const step = steps[i]
  const first = auth.user?.firstName || ''

  React.useEffect(() => {
    let live = true
    getOrganizationMembers().then(x => { if (live) setMe((x.members || []).find(m => m.id === auth.user?.id) || null) }).catch(() => {})
    return () => { live = false }
  }, [auth.user?.id])

  const measure = React.useCallback(() => {
    const rail = document.querySelector('.app-nav-rail')
    const find = (sel) => { const el = rail && sel.startsWith('[title') ? rail.querySelector(sel) : document.querySelector(sel); return el && el.getBoundingClientRect() }
    const out = []
    if (step.target) {
      const r = find(`[title="${step.target}"]`)
      if (r && r.width) out.push({ box: r, pad: 3 })
      ;(step.extra || []).forEach(sel => { const e = find(sel); if (e && e.width) out.push({ box: e, pad: 4, extra: true }) })
    }
    setRects(out)
    const ps = []
    ;['My Coverage', 'Stocks', 'Assistant'].forEach(t => { const r = rail && rail.querySelector(`[title="${t}"]`); if (r) { const b = r.getBoundingClientRect(); ps.push({ x: b.right - 9, y: b.top + 3, key: t }) } })
    setPips(ps)
  }, [step])

  React.useEffect(() => {
    if (step.view) onNavigate(step.view)
    else if (step.kind === 'welcome') onNavigate(analyst ? 'coverage' : 'dashboard')
    const t = setTimeout(measure, 160)
    return () => clearTimeout(t)
  }, [i])  // eslint-disable-line react-hooks/exhaustive-deps

  React.useEffect(() => {
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [measure])

  const go = (n) => setI(Math.max(0, Math.min(steps.length - 1, n)))
  React.useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowRight') go(i + 1)
      else if (e.key === 'ArrowLeft') go(i - 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })
  React.useEffect(() => { const b = cardRef.current && cardRef.current.querySelector('.wt-btn.primary'); if (b) b.focus({ preventScroll: true }) }, [i])

  const finish = () => { onNavigate(analyst ? 'coverage' : 'dashboard'); onClose() }
  const centered = !step.target
  const asideCount = steps.length - 1
  const nav = <div className="wt-foot">
    <button className="wt-btn" disabled={i === 0} onClick={() => go(i - 1)}>Back</button>
    <button className="wt-btn primary" onClick={() => go(i + 1)}>Next</button>
    <button className="wt-link" onClick={onClose}>Skip tour</button>
    <span className="wt-count">{i} of {asideCount}</span>
  </div>

  let body
  if (step.kind === 'welcome') {
    body = <><h2>Welcome{first ? `, ${first}` : ''}.</h2>
      <p className="wt-lede">Your account is ready. This two-minute tour shows where everything is and what to open first.</p>
      <div className="wt-facts">
        <div className="wt-fact"><span>Your role</span><b>{ROLE_NAME[role] || 'Member'}</b></div>
        {me && me.sectors && me.sectors.length > 0 && <div className="wt-fact"><span>{me.sectors.length > 1 ? 'Your sectors' : 'Your sector'}</span><b>{me.sectors.join(', ')}</b></div>}
        {me && me.coverage && analyst && <div className="wt-fact"><span>Companies you cover</span><b>{me.coverage.length}</b></div>}
      </div>
      <p className="wt-tip"><b>Set from your invitation.</b> If anything here looks wrong, ask an admin to update it.</p></>
  } else if (step.kind === 'week') {
    body = <><h2>A normal week</h2><p className="wt-lede">The terminal fits a simple weekly rhythm.</p>
      {leader
        ? pts([<><b>Thursday evening.</b> Analysts submit their digests by 5:00 pm Pacific.</>, <><b>Thursday to Friday.</b> Read each digest, comment on items, and acknowledge it.</>])
        : <><div className="wt-week"><div className="wt-day"><b>Mon</b>Read the news</div><div className="wt-day"><b>Tue</b>Flag items</div><div className="wt-day"><b>Wed</b>Add notes</div><div className="wt-day due"><b>Thu</b>Submit by 5 pm</div><div className="wt-day"><b>Fri</b>Read replies</div></div>
          {pts([<><b>Monday to Wednesday.</b> Read the news on your companies and flag what matters, with a note.</>, <><b>Thursday by 5:00 pm.</b> Review your digest and submit it to your sector leader.</>, <><b>Friday.</b> Open the Inbox for acknowledgements and questions.</>])}</>}
      <p className="wt-tip"><b>The Assistant is open all week.</b> Use it whenever you want a second pair of eyes on a company or a fund.</p></>
  } else if (step.kind === 'done') {
    body = <><h2>You are set.</h2>
      <p className="wt-lede">{analyst ? 'Start in My Coverage and flag your first item.' : 'Start on Funds to see how both portfolios are doing.'} You can replay this tour any time from your profile menu.</p>
      <div className="wt-facts"><div className="wt-fact"><span>Open first</span><b>{analyst ? 'My Coverage' : 'Funds'}</b></div><div className="wt-fact"><span>Ask anything</span><b>Assistant</b></div><div className="wt-fact"><span>Replay this tour</span><b>Profile menu</b></div></div></>
  } else {
    body = <>{step.best ? <span className="wt-tag">● {step.best}</span> : <span className="wt-tag plain">Tab</span>}
      <h2>{step.label}</h2><p className="wt-lede">{step.lede}</p>{pts(step.pts)}<p className="wt-tip">{step.tip}</p></>
  }
  const foot = step.kind === 'welcome'
    ? <div className="wt-foot"><button className="wt-btn primary" onClick={() => go(1)}>Start the tour</button><button className="wt-btn" onClick={onClose}>Skip for now</button></div>
    : step.kind === 'done'
      ? <div className="wt-foot"><button className="wt-btn primary" onClick={finish}>{analyst ? 'Open My Coverage' : 'Go to Funds'}</button><button className="wt-btn" onClick={() => go(i - 1)}>Back</button></div>
      : nav

  const px = ({ box, pad }) => ({ left: box.left - pad, top: box.top - pad, width: box.width + pad * 2, height: box.height + pad * 2 })
  return <div className="wt">
    <div className="wt-block" />
    {rects.length === 0 && <div className="wt-dim" />}
    {rects.map((r, n) => <div key={n} className={'wt-spot' + (r.extra ? ' extra' : '')} style={px(r)} />)}
    {rects.length > 0 && pips.map(p => <span key={p.key} className="wt-pip" style={{ left: p.x, top: p.y }} />)}
    <div ref={cardRef} className={'wt-card ' + (centered ? 'center' : 'dock')} role="dialog" aria-modal="true" aria-label="Welcome tour">
      <div className="wt-body">{body}</div>
      <div className="wt-dots" role="tablist" aria-label="Tour progress">{steps.map((x, k) => <button key={x.id} className={'wt-dot ' + (k < i ? 'done' : k === i ? 'now' : '')} role="tab" aria-selected={k === i} aria-label={`Step ${k + 1}`} onClick={() => go(k)} />)}</div>
      {foot}
    </div>
  </div>
}
