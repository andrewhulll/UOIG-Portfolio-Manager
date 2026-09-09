import React from 'react'
import { acknowledge, addComment, getFlags, getInbox, getQueue, markRead, removeFlag, saveFlag, submitDraft } from './api.js'
import { getMyCoverage, getQuote, getSeries } from '../api.js'
import { PriceChart } from '../charts/PriceChart.jsx'
import { SECTOR_COLORS } from '../ui.js'
import './submissions.css'

const initials = name => { const p = (name || '').trim().split(/\s+/); return ((p[0]?.[0] || '') + (p[1]?.[0] || '')).toUpperCase() || '?' }
function Avatar({ name, color = '#5a93f9' }) {
  return <span className="submission-avatar" style={{ color, borderColor: color + '55', background: color + '1c' }}>{initials(name)}</span>
}
function SectorChip({ sector }) {
  if (!sector) return null
  const color = SECTOR_COLORS[sector] || '#6b7794'
  return <span className="submission-sector-chip" style={{ color, background: color + '18', borderColor: color + '40' }}>{sector}</span>
}

export const isAnalyst = auth => ['member', 'analyst'].includes(auth?.role)
const canReview = auth => auth?.role === 'sector-leader' || auth?.canInvite || auth?.role === 'admin'
const displayStatus = status => ({ draft: 'Draft', pending: 'Pending', submitted: 'Submitted', acked: 'Acknowledged' })[status] || status
const dateLabel = value => new Date(value).toLocaleString('en-US', { timeZone: 'America/Los_Angeles', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + ' PT'
const sign = (v, dp = 1) => (v >= 0 ? '+' : '') + v.toFixed(dp) + '%'
const shiftWeek = (week, days) => { const d = new Date(week + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10) }

function useRemote(fetcher, deps = []) {
  const [data, setData] = React.useState(null)
  const [error, setError] = React.useState('')
  const [version, reload] = React.useReducer(n => n + 1, 0)
  React.useEffect(() => {
    let live = true
    setData(null)
    const load = () => fetcher().then(result => { if (live) { setData(result); setError('') } }).catch(e => { if (live) setError(e.message) })
    load()
    const poll = setInterval(load, 30000)
    return () => { live = false; clearInterval(poll) }
  }, [...deps, version])
  return { data, error, reload }
}

// Coverage bundle (price/MTD/next-earnings) for the analyst's own covered names —
// cheap, fetched once and reused across every item card instead of a per-item call.
function useCoverageMap() {
  const [map, setMap] = React.useState({})
  React.useEffect(() => {
    let live = true
    getMyCoverage().then(data => { if (live) setMap(Object.fromEntries((data.tickers || []).map(t => [t.ticker, t]))) }).catch(() => {})
    return () => { live = false }
  }, [])
  return map
}

// Live quote (for tickers outside the analyst's coverage) + 1-month price series for
// the mini chart, one fetch per unique ticker, deduped for the life of the component.
function useTickerContext(tickers, coverageMap) {
  const [state, setState] = React.useState({})
  const fetched = React.useRef(new Set())
  React.useEffect(() => {
    let live = true
    tickers.forEach(ticker => {
      if (!ticker || fetched.current.has(ticker)) return
      fetched.current.add(ticker)
      Promise.all([
        coverageMap[ticker] ? Promise.resolve(null) : getQuote(ticker).catch(() => null),
        getSeries(ticker, '1M').catch(() => null),
      ]).then(([quote, series]) => { if (live) setState(s => ({ ...s, [ticker]: { quote, series } })) })
    })
    return () => { live = false }
  })
  return state
}

function ErrorNotice({ error }) { return error ? <p className="submission-error" role="alert">{error}</p> : null }
function Status({ value }) { return <span className={`submission-chip ${value}`}>{displayStatus(value)}</span> }

function Deadline({ data }) {
  const [now, setNow] = React.useState(Date.now())
  React.useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 30000); return () => clearInterval(timer) }, [])
  const minutes = Math.ceil((new Date(data.dueAt).getTime() - now) / 60000)
  const remaining = minutes <= 0 ? 'Past due · submissions still open' : `${Math.floor(minutes / 1440)}d ${Math.floor(minutes % 1440 / 60)}h ${minutes % 60}m left`
  return <span className="submission-deadline">Due Thursday 5:00pm PT · {data.week === data.currentWeek ? remaining : dateLabel(data.dueAt)}</span>
}

function WeekPicker({ data, onChange }) {
  const shift = days => { const next = new Date(data.week + 'T12:00:00Z'); next.setUTCDate(next.getUTCDate() + days); onChange(next.toISOString().slice(0, 10)) }
  return <div className="submission-week"><button aria-label="Previous week" onClick={() => shift(-7)}>←</button><span>Week of {data.week}</span><button aria-label="Next week" disabled={data.week >= data.currentWeek} onClick={() => shift(7)}>→</button>{data.week !== data.currentWeek && <button onClick={() => onChange('')}>This week</button>}</div>
}

function Item({ item, extra, children }) {
  return <li className="submission-item">
    <div className="submission-item-title">{item.ticker && <b>{item.ticker}</b>}{/^https?:\/\//i.test(item.url || '') ? <a href={item.url} target="_blank" rel="noreferrer">{item.title} ↗</a> : <span>{item.title}</span>}</div>
    {item.note && <p className="submission-note">{item.note}</p>}{extra}{children}
  </li>
}

// Price/MTD/earnings snapshot + a small 1-month chart for an item's ticker, so an
// analyst can reference the move and any upcoming catalyst without leaving the draft.
function TickerStrip({ ticker, coverageMap, ctxState, lastNote }) {
  if (!ticker) return null
  const cov = coverageMap[ticker]
  const ctx = ctxState[ticker] || {}
  const price = cov ? cov.price : ctx.quote?.px
  const dayChangePct = cov ? cov.dayChangePct : ctx.quote?.chg
  const mtdChangePct = cov?.mtdChangePct
  const nextEarnings = cov?.nextEarnings
  const earningsInDays = cov?.earningsInDays
  const soon = earningsInDays != null && earningsInDays >= 0 && earningsInDays <= 5
  const up = dayChangePct != null && dayChangePct >= 0
  const values = ctx.series?.close || []
  const dates = ctx.series?.dates || []
  return <div className="submission-ticker">
    <div className="submission-ticker-stats">
      <span className="submission-ticker-price">{price != null ? '$' + Number(price).toFixed(2) : '—'}</span>
      <span className={`submission-ticker-chg ${dayChangePct == null ? '' : (up ? 'up' : 'down')}`}>{dayChangePct != null ? sign(dayChangePct) : '—'}</span>
      <span className="submission-muted">MTD {mtdChangePct != null ? sign(mtdChangePct) : '—'}</span>
      <span className={`submission-ticker-earnings${soon ? ' soon' : ''}`}>{nextEarnings ? `Earnings ${nextEarnings} · in ${earningsInDays}d` : 'No earnings date on file'}</span>
    </div>
    {values.length > 1 && <div className="submission-ticker-chart"><PriceChart dates={dates} values={values} color={dayChangePct == null ? '#6b7794' : (up ? '#21d07a' : '#ff5666')} height={64} /></div>}
    {lastNote && <p className="submission-lastweek">Last week's note: {lastNote}</p>}
  </div>
}

// Sector-lead <-> analyst feedback thread on a submitted digest. Read-only once
// rendered for the analyst; sector leaders (and admins) get the reply form.
function CommentThread({ comments, canComment, onAdd }) {
  const [text, setText] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState('')
  const submit = async e => {
    e.preventDefault()
    if (!text.trim()) return
    setBusy(true); setError('')
    try { await onAdd(text.trim()); setText('') } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  if (!comments?.length && !canComment) return null
  return <div className="submission-comments">
    {comments?.length > 0 && <ul className="submission-comment-list">
      {comments.map(c => <li key={c.id} className="submission-comment"><div className="submission-comment-meta"><b>{c.authorName}</b><span className="submission-muted"> · {dateLabel(c.created_at)}</span></div><p>{c.body}</p></li>)}
    </ul>}
    {canComment && <form className="submission-comment-form" onSubmit={submit}>
      <textarea rows={2} maxLength={2000} value={text} onChange={e => setText(e.target.value)} placeholder="Add a comment for the analyst…" disabled={busy} />
      <div className="submission-actions"><button className="primary" disabled={busy || !text.trim()}>{busy ? 'Posting…' : 'Comment'}</button></div>
      <ErrorNotice error={error} />
    </form>}
  </div>
}

function ItemForm({ initial, sector, busy, onSave, onCancel }) {
  const [title, setTitle] = React.useState(initial?.title || '')
  const [ticker, setTicker] = React.useState(initial?.ticker || '')
  const [url, setUrl] = React.useState(initial?.url || '')
  const [note, setNote] = React.useState(initial?.note || '')
  return <form className="submission-form" onSubmit={e => { e.preventDefault(); onSave({ title: title.trim(), ticker: ticker.trim() || null, url: url.trim() || null, note: note.trim(), sector }, initial?.id) }}>
    <label>Headline or summary title<input required maxLength={500} value={title} onChange={e => setTitle(e.target.value)} placeholder="What should your sector lead know?" /></label>
    <div className="submission-form-row"><label>Ticker (optional)<input maxLength={12} value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} placeholder="AAPL" /></label><label>News link (optional)<input type="url" maxLength={2048} value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…" /></label></div>
    <label>Note or your own summary<textarea maxLength={5000} rows={3} value={note} onChange={e => setNote(e.target.value)} placeholder="Explain the news and why it matters for your coverage." /></label>
    <div className="submission-actions"><button className="primary" disabled={busy || !title.trim()}>{busy ? 'Saving…' : initial ? 'Save changes' : 'Add to draft'}</button><button type="button" disabled={busy} onClick={onCancel}>Cancel</button></div>
  </form>
}

export function WeeklySubmission({ auth }) {
  const [week, setWeek] = React.useState('')
  const [sector, setSector] = React.useState('')
  const [editor, setEditor] = React.useState(null)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState('')
  const remote = useRemote(() => getFlags(week), [week])
  const coverageMap = useCoverageMap()
  const data = remote.data
  const prevWeek = data ? shiftWeek(data.week, -7) : null
  const prevRemote = useRemote(() => prevWeek ? getFlags(prevWeek) : Promise.resolve(null), [prevWeek])
  const sectors = data ? [...new Set([...data.sectors, ...data.submissions.map(s => s.sector), ...data.flags.map(f => f.sector)])] : []
  const selected = sectors.includes(sector) ? sector : sectors[0] || ''
  const draft = data?.submissions.find(s => s.sector === selected)
  const flags = data?.flags.filter(f => f.sector === selected) || []
  const prevFlags = prevRemote.data?.flags.filter(f => f.sector === selected) || []
  const lastNoteFor = ticker => prevFlags.find(f => f.ticker === ticker)?.note || null
  const tickers = [...new Set(flags.map(f => f.ticker).filter(Boolean))]
  const ctxState = useTickerContext(tickers, coverageMap)
  if (!isAnalyst(auth)) return null
  const editable = data && data.week === data.currentWeek && data.sectors.includes(selected) && (!draft || draft.status === 'draft')
  const changeWeek = value => { setWeek(value); setEditor(null); setError('') }
  const act = async action => {
    setBusy(true); setError('')
    try { await action(); setEditor(null); remote.reload() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <section className="submissions weekly-submission" aria-label="This week's submission">
    <div className="submission-heading"><div><div className="submission-eyebrow">Weekly sector update</div><h2>This week's submission</h2></div><button onClick={remote.reload} disabled={busy}>Refresh</button></div>
    <ErrorNotice error={error || remote.error} />
    {!data ? <p role="status">{remote.error ? 'Could not load your draft. Use Refresh to try again.' : 'Loading your draft…'}</p> : <>
      <div className="submission-toolbar"><WeekPicker data={data} onChange={changeWeek} /><Deadline data={data} /></div>
      {!sectors.length ? <p>No sector assigned. Ask an admin to update your coverage in the directory.</p> : <>
        <div className="submission-toolbar"><label>Sector <select value={selected} disabled={busy} onChange={e => { setSector(e.target.value); setEditor(null); setError('') }}>{sectors.map(s => <option key={s}>{s}</option>)}</select></label><Status value={draft?.status || 'draft'} /></div>
        {draft?.submitted_at && <p className="submission-muted">Sent to sector leaders' inboxes {dateLabel(draft.submitted_at)}. {draft.status === 'acked' ? `Acknowledged ${dateLabel(draft.acked_at)}.` : 'Awaiting acknowledgement.'}</p>}
        {draft?.comments?.length > 0 && <div className="submission-lead-feedback"><h4>Sector lead feedback</h4><CommentThread comments={draft.comments} canComment={false} /></div>}
        <ul className="submission-items">{flags.map(item => <Item key={item.id} item={item}
          extra={item.ticker && <TickerStrip ticker={item.ticker} coverageMap={coverageMap} ctxState={ctxState} lastNote={lastNoteFor(item.ticker)} />}>
          {editable && <div className="submission-actions"><button disabled={busy} onClick={() => setEditor(item)}>Edit</button><button disabled={busy} onClick={() => act(() => removeFlag(item.id))}>Remove</button></div>}</Item>)}</ul>
        {!flags.length && <p className="submission-muted">Flag articles from a stock's News tab or write your own summary here.</p>}
        {editable && <>{editor ? <ItemForm key={`${selected}:${editor.id || 'new'}`} initial={editor.id ? editor : null} sector={selected} busy={busy} onSave={(body, id) => act(() => saveFlag(body, id))} onCancel={() => setEditor(null)} /> : <div className="submission-actions"><button disabled={busy} onClick={() => setEditor({})}>+ Write a summary</button><button className="primary" disabled={busy || !flags.length} onClick={() => act(() => submitDraft(selected))}>{busy ? 'Submitting…' : 'Submit to sector lead'}</button></div>}
          <p className="submission-muted">Submitting sends this sector's items to its leaders' in-app inboxes and makes the draft read-only.</p>
        </>}
      </>}
    </>}
  </section>
}

function FlagAction({ item, ticker, data, reload }) {
  const [open, setOpen] = React.useState(false)
  const [note, setNote] = React.useState('')
  const [sector, setSector] = React.useState(data.coverage?.find(c => c.ticker === ticker)?.sector || data.sectors[0] || '')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState('')
  const flag = data.flags.find(f => f.url === item.link && f.sector === sector)
  const sent = data.submissions.some(s => s.sector === sector && s.status !== 'draft')
  const save = async e => {
    e.preventDefault(); setBusy(true); setError('')
    try { await saveFlag({ title: item.title, url: item.link, ticker, note, sector }, flag?.id); setOpen(false); reload() } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return <div className="submission-flag">
    <button disabled={!data.sectors.length} aria-expanded={open} onClick={() => { setOpen(!open); setNote(flag?.note || '') }}>{flag ? '✓ Flagged for sector lead' : '⚑ Flag for sector lead'}</button>
    {open && <form className="submission-form" onSubmit={save}>
      <label>Sector<select value={sector} disabled={busy} onChange={e => { setSector(e.target.value); setNote(data.flags.find(f => f.url === item.link && f.sector === e.target.value)?.note || '') }}>{data.sectors.map(s => <option key={s}>{s}</option>)}</select></label>
      {sent ? <p>This sector's digest has been submitted and is read-only.</p> : <><label>Note (optional)<input value={note} maxLength={5000} onChange={e => setNote(e.target.value)} placeholder="Why does this matter?" /></label><button className="primary" disabled={busy}>{busy ? 'Saving…' : flag ? 'Update note' : 'Add to this week'}</button></>}
      <ErrorNotice error={error} />
    </form>}
  </div>
}

function AnalystNews({ news, ticker }) {
  const remote = useRemote(getFlags, [ticker])
  return <div className="submissions"><ErrorNotice error={remote.error} />{remote.error && <button onClick={remote.reload}>Retry flag status</button>}
    {news.map((item, i) => <article className="submission-news" key={item.link || i}><a href={/^https?:\/\//i.test(item.link || '') ? item.link : undefined} target="_blank" rel="noreferrer">{item.title}</a><p className="submission-muted">{item.publisher} · {item.ago}</p>{remote.data && /^https?:\/\//i.test(item.link || '') && <FlagAction item={item} ticker={ticker} data={remote.data} reload={remote.reload} />}</article>)}
  </div>
}

export function NewsList({ auth, news, ticker }) {
  if (isAnalyst(auth)) return <AnalystNews news={news} ticker={ticker} />
  return <div className="submissions">{news.map((item, i) => <article className="submission-news" key={item.link || i}><a href={/^https?:\/\//i.test(item.link || '') ? item.link : undefined} target="_blank" rel="noreferrer">{item.title}</a><p className="submission-muted">{item.publisher} · {item.ago}</p></article>)}</div>
}

function DigestCard({ submission, auth, onAck, onComment, busy, children }) {
  return <article className="submission-digest"><div className="submission-heading"><div className="submission-digest-who">
      <Avatar name={submission.analyst} color={SECTOR_COLORS[submission.sector] || '#5a93f9'} />
      <div><h3>{submission.analyst}</h3><p className="submission-muted"><SectorChip sector={submission.sector} /> · Week of {submission.week_of}</p></div>
    </div><Status value={submission.status} /></div>
    <ul className="submission-items">{submission.items.map(item => <Item key={item.id} item={item} />)}</ul>
    {submission.status === 'acked' && <p className="submission-muted">Acknowledged {dateLabel(submission.acked_at)}</p>}
    <div className="submission-actions">{canReview(auth) && submission.status === 'submitted' && <button className="primary" disabled={busy} onClick={() => onAck(submission.id)}>Acknowledge</button>}{children}</div>
    {submission.status !== 'draft' && onComment && <CommentThread comments={submission.comments} canComment={canReview(auth)} onAdd={text => onComment(submission.id, text)} />}
  </article>
}

function SectorQueue({ auth }) {
  const [week, setWeek] = React.useState('')
  const [sector, setSector] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState('')
  const remote = useRemote(() => getQueue(week), [week])
  const data = remote.data
  const ack = async id => { setBusy(true); setError(''); try { await acknowledge(id); remote.reload() } catch (e) { setError(e.message) } finally { setBusy(false) } }
  const comment = (id, text) => addComment(id, text).then(() => remote.reload())
  const board = data?.board.filter(row => !sector || row.sector === sector) || []
  const sent = data?.submissions.filter(row => !sector || row.sector === sector) || []
  return <><div className="submission-toolbar"><h2>Sector submissions</h2><button onClick={remote.reload}>Refresh</button></div><ErrorNotice error={error || remote.error} />
    {!data ? <p role="status">{remote.error ? 'Could not load submissions.' : 'Loading sector submissions…'}</p> : <>
      <div className="submission-toolbar"><WeekPicker data={data} onChange={setWeek} /><label>Sector <select value={sector} onChange={e => setSector(e.target.value)}><option value="">All assigned sectors</option>{data.sectors.map(s => <option key={s}>{s}</option>)}</select></label></div>
      <Deadline data={data} />
      <h3>{board.filter(row => row.status !== 'pending').length} of {board.length} analyst assignments submitted</h3>
      <div className="submission-table-wrap"><table><thead><tr><th>Analyst</th><th>Sector</th><th>Status</th></tr></thead><tbody>{board.map(row => <tr key={`${row.user_id}:${row.sector}`}><td>{row.analyst}</td><td>{row.sector}</td><td><Status value={row.status} /></td></tr>)}</tbody></table></div>
      {!board.length && <p className="submission-muted">No analysts assigned to these sectors.</p>}
      {sent.map(submission => <DigestCard key={submission.id} submission={submission} auth={auth} onAck={ack} onComment={comment} busy={busy} />)}
      {!sent.length && <p className="submission-muted">No submissions received for this week yet.</p>}
    </>}
  </>
}

export function InboxPage({ auth }) {
  const [tab, setTab] = React.useState('messages')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState('')
  const remote = useRemote(getInbox)
  const act = async action => { setBusy(true); setError(''); try { await action(); remote.reload() } catch (e) { setError(e.message) } finally { setBusy(false) } }
  const messages = remote.data?.messages || []
  const groups = messages.reduce((all, m) => { (all[m.user_id] ||= []).push(m); return all }, {})
  return <section className="submissions inbox-page">
    <div className="submission-heading"><div><div className="submission-eyebrow">Team updates</div><h1>Inbox {remote.data?.unread > 0 && <span className="submission-chip">{remote.data.unread} unread</span>}</h1><p className="submission-muted">Sector updates and acknowledgements, shared inside UOIG.</p></div><button disabled={busy} onClick={remote.reload}>Refresh</button></div>
    {canReview(auth) && <div className="submission-tabs"><button aria-pressed={tab === 'messages'} onClick={() => setTab('messages')}>My inbox</button><button aria-pressed={tab === 'queue'} onClick={() => setTab('queue')}>Sector submissions</button></div>}
    {tab === 'queue' ? <SectorQueue auth={auth} /> : <><ErrorNotice error={error || remote.error} />
      {!remote.data ? <p role="status">{remote.error ? 'Could not load your inbox. Use Refresh to try again.' : 'Loading inbox…'}</p> : !messages.length ? <div className="submission-empty">
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="2.5" /><path d="M3.5 6.5 12 13l8.5-6.5" /><path d="m15 15.5 2 2 3.5-3.5" /></svg>
          <h2>Your inbox is clear</h2><p>{isAnalyst(auth) ? 'When a sector lead acknowledges your weekly submission, it will appear here.' : 'Submitted digests for your assigned sectors will appear here.'}</p></div>
        : Object.entries(groups).map(([uid, group]) => <div key={uid} className="submission-message-group">
          <div className="submission-group-head"><Avatar name={group[0].analyst} color={SECTOR_COLORS[group[0].sector] || '#5a93f9'} /><h2>{group[0].analyst}</h2></div>
          {group.map(message => <div className={message.read_at ? '' : 'submission-unread'} key={message.message_id}>
        <p className="submission-message-label">{!message.read_at && <span className="submission-unread-dot" />}{message.kind === 'ack' ? `${message.ackedByName} acknowledged your submission` : 'New sector submission'} · {dateLabel(message.created_at)}</p>
        <DigestCard submission={message} auth={auth} busy={busy} onAck={id => act(() => acknowledge(id))} onComment={(id, text) => addComment(id, text).then(() => remote.reload())}>{!message.read_at && <button disabled={busy} onClick={() => act(() => markRead(message.message_id))}>Mark as read</button>}</DigestCard>
      </div>)}</div>)}
    </>}
  </section>
}
