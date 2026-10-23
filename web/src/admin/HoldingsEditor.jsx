import React from 'react'
import { getAdminHoldings, previewHoldingChanges, applyHoldingChanges } from '../api.js'
import './admin.css'

const KINDS = [
  ['buy_new', 'Buy new', 'buy'],
  ['buy', 'Add to', 'buy'],
  ['trim', 'Trim', 'sell'],
  ['sell_all', 'Sell out', 'sell'],
  ['cash', 'Cash', 'cash'],
]
const money = (n) => (n < 0 ? '−$' : '$') + Math.abs(Number(n)).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const qty = (n) => Number(n).toLocaleString(undefined, { maximumFractionDigits: 4 })
const side = (kind) => (kind === 'buy_new' || kind === 'buy' ? 'buy' : kind === 'cash' ? 'cash' : 'sell')
const blankLegs = (funds, on) => Object.fromEntries(funds.map(f => [f.name, { on: f.name === on, shares: '', route: 'cash' }]))
const blank = (funds, fund, kind = 'trim') => ({ fund, kind, ticker: '', price: '', amount: '', direction: 'deposit', name: '', sector: '', cap_class: '', legs: blankLegs(funds, fund) })
const routeLabel = (r) => (r === 'cash' ? 'cash' : r === 'none' ? 'nowhere' : r)
const KIND_NAME = { buy_new: 'Buy', buy: 'Add', trim: 'Trim', sell_all: 'Sell out' }

function Field({ label, hint, children }) {
  return <label className="ad-field"><span>{label}</span>{children}{hint && <div className="ad-hint">{hint}</div>}</label>
}

export function HoldingsEditor() {
  const [data, setData] = React.useState(null)
  const [error, setError] = React.useState('')
  const [draft, setDraft] = React.useState(null)
  const [batch, setBatch] = React.useState([])
  const [note, setNote] = React.useState('')
  const [formError, setFormError] = React.useState('')
  const [review, setReview] = React.useState(null)  // { preview, understood, busy, error }
  const [done, setDone] = React.useState('')
  const load = React.useCallback(() => getAdminHoldings().then(x => { setData(x); setDraft(d => d || blank(x.funds, x.funds[0]?.name)); setError('') }).catch(e => setError(e.detail || 'Could not load holdings')), [])
  React.useEffect(() => { load() }, [load])

  if (!data || !draft) return <div className="settings-card settings-empty">{error ? <><b>Holdings unavailable</b><span>{error}</span><button onClick={load}>Try again</button></> : <><span className="settings-spinner" />Loading holdings…</>}</div>

  const isCash = draft.kind === 'cash'
  const fund = data.funds.find(f => f.name === draft.fund) || data.funds[0]
  const cash = fund.positions.find(p => p.sec_type === 'cash')
  const activeFunds = isCash ? [fund] : data.funds.filter(f => draft.legs[f.name]?.on)
  const heldIn = (f, ticker) => f.positions.find(p => p.ticker === ticker && p.sec_type !== 'cash')
  const options = new Map()
  activeFunds.forEach(f => f.positions.filter(p => p.sec_type !== 'cash').forEach(p => { if (!options.has(p.ticker)) options.set(p.ticker, p) }))
  const needsPosition = ['buy', 'trim', 'sell_all'].includes(draft.kind)
  const buying = draft.kind === 'buy' || draft.kind === 'buy_new'
  const routesFor = (f) => [['cash', 'Cash'], ...f.positions.filter(p => p.sec_type === 'etf').map(p => [p.ticker, `${p.ticker} index`]), ['none', "Don't adjust"]]
  const set = (patch) => { setDraft(d => ({ ...d, ...patch })); setFormError('') }
  const setLeg = (name, patch) => { setDraft(d => ({ ...d, legs: { ...d.legs, [name]: { ...d.legs[name], ...patch } } })); setFormError('') }
  const pickPosition = (ticker) => { const p = options.get(ticker); set({ ticker, price: p?.price ? String(Number(p.price.toFixed(2))) : '' }) }
  const changeKind = (kind) => setDraft(d => ({ ...blank(data.funds, d.fund, kind), legs: Object.fromEntries(data.funds.map(f => [f.name, { on: d.legs[f.name]?.on ?? false, shares: '', route: 'cash' }])) }))

  // The ticket: what this leg moves, and where the money lands.
  const ticket = (f, leg) => {
    const price = Number(draft.price)
    const pos = heldIn(f, draft.ticker.trim().toUpperCase())
    const shares = draft.kind === 'sell_all' ? pos?.shares : Number(leg.shares)
    if (!(price > 0) || !(shares > 0)) return null
    const value = shares * price
    const fcash = f.positions.find(p => p.sec_type === 'cash')
    if (leg.route === 'none') return { cls: side(draft.kind), text: <><b>{money(value)}</b> {buying ? 'spent' : 'raised'}; cash and index stay as they are</> }
    if (leg.route === 'cash') {
      const after = (fcash?.shares || 0) + (buying ? -value : value)
      return { cls: side(draft.kind), bad: after < 0, text: <><b>{money(value)}</b> {buying ? 'from' : 'to'} cash · balance {money(fcash?.shares || 0)} → <b>{money(after)}</b>{after < 0 ? ' — not enough cash' : ''}</> }
    }
    const idx = f.positions.find(p => p.ticker === leg.route)
    const units = idx?.price ? value / idx.price : null
    if (!units) return { cls: side(draft.kind), text: <><b>{money(value)}</b> via {leg.route} (no stored price yet)</> }
    const after = idx.shares + (buying ? -units : units)
    return { cls: side(draft.kind), bad: after < 0, text: <><b>{money(value)}</b> {buying ? 'raised by selling' : 'into'} <b>{qty(units)} sh {leg.route}</b> at {money(idx.price)} · holding {qty(idx.shares)} → <b>{qty(after)}</b>{after < 0 ? ' — not enough index' : ''}</> }
  }

  const addToBatch = () => {
    const n = (v) => Number(v)
    const c = draft
    if (isCash) {
      if (!(n(c.amount) > 0)) return setFormError('Enter a cash amount greater than zero')
      setBatch(b => [...b, { fund: c.fund, kind: 'cash', direction: c.direction, amount: c.amount, ticker: '', shares: '', price: '' }])
    } else {
      if (!activeFunds.length) return setFormError('Choose at least one fund')
      if (!c.ticker.trim()) return setFormError(needsPosition ? 'Choose a position' : 'Enter a ticker')
      if (!(n(c.price) > 0)) return setFormError('Enter the execution price')
      if (c.kind === 'buy_new' && (!c.name.trim() || !c.sector || !c.cap_class) && !data.funds.some(f => heldIn(f, c.ticker.trim().toUpperCase())))
        return setFormError('A stock new to the platform needs a company name, sector and cap class')
      const out = []
      for (const f of activeFunds) {
        const leg = c.legs[f.name]
        const pos = heldIn(f, c.ticker.trim().toUpperCase())
        if (c.kind === 'buy_new' && pos) return setFormError(`${f.name} already holds ${c.ticker.toUpperCase()} — use Add to`)
        if (c.kind !== 'buy_new' && !pos) return setFormError(`${f.name} does not hold ${c.ticker}`)
        if (c.kind !== 'sell_all' && !(n(leg.shares) > 0)) return setFormError(`Enter shares for ${f.name}`)
        if (c.kind === 'trim' && n(leg.shares) >= pos.shares) return setFormError(`${f.name}: a trim must be under ${qty(pos.shares)} shares — use Sell out to close it`)
        out.push({ fund: f.name, kind: c.kind, ticker: c.ticker, shares: leg.shares, price: c.price, route: leg.route, name: c.name, sector: c.sector, cap_class: c.cap_class })
      }
      setBatch(b => [...b, ...out])
    }
    setDraft(blank(data.funds, c.fund, c.kind)); setFormError(''); setDone('')
  }

  const body = () => ({ changes: batch.map(c => ({ ...c, ticker: c.ticker.trim().toUpperCase(), shares: Number(c.shares), price: Number(c.price), amount: Number(c.amount) })), note })
  const startReview = async () => {
    setFormError('')
    try { setReview({ preview: await previewHoldingChanges(body()), understood: false, busy: false, error: '' }) }
    catch (e) { setFormError(e.detail || 'Could not preview these changes') }
  }
  const apply = async () => {
    setReview(r => ({ ...r, busy: true, error: '' }))
    try {
      await applyHoldingChanges(body())
      const n = batch.length
      setReview(null); setBatch([]); setNote(''); setDone(`Applied ${n} change${n === 1 ? '' : 's'}. Positions and cash are updated.`)
      await load()
    } catch (e) { setReview(r => ({ ...r, busy: false, error: e.detail || 'Could not apply changes' })) }
  }

  const ledgerDetail = (c) => {
    if (c.kind === 'cash') return { tag: 'cash', label: 'Cash', main: <>{c.direction === 'deposit' ? 'Deposit into' : 'Withdraw from'} <b>{c.fund}</b></>, sub: '', num: money(c.amount) }
    const sh = c.kind === 'sell_all' ? 'all shares' : `${qty(c.shares)} sh`
    const via = buying_(c.kind) ? `funded from ${routeLabel(c.route)}` : `proceeds to ${routeLabel(c.route)}`
    return { tag: side(c.kind), label: KIND_NAME[c.kind], main: <><b>{c.ticker.toUpperCase()}</b> in {c.fund}</>, sub: `${sh} at ${money(c.price)} · ${via}`, num: c.kind === 'sell_all' ? '' : money(Number(c.shares) * Number(c.price)) }
  }
  const buying_ = (k) => k === 'buy' || k === 'buy_new'

  const byFund = review ? Object.entries(review.preview.positions.reduce((m, p) => { (m[p.fund] = m[p.fund] || []).push(p); return m }, {})) : []
  const open = review && !review.busy

  return <div className="settings-card ad">
    <div className="settings-section-head"><div><div className="settings-card-title">Update holdings</div><div className="settings-muted">Record trades and cash moves. Nothing changes until you review and confirm.</div></div></div>

    <div className="ad-seg" role="group" aria-label="Action">
      {KINDS.map(([k, label, sd]) => <button key={k} type="button" data-side={sd} aria-pressed={draft.kind === k} onClick={() => changeKind(k)}>{label}</button>)}
    </div>

    <div className="ad-grid">
      {isCash ? <>
        <Field label="Fund"><select value={draft.fund} onChange={e => set({ fund: e.target.value })}>{data.funds.map(f => <option key={f.name}>{f.name}</option>)}</select></Field>
        <Field label="Move"><select value={draft.direction} onChange={e => set({ direction: e.target.value })}><option value="deposit">Deposit</option><option value="withdraw">Withdraw</option></select></Field>
        <Field label="Amount ($)" hint={`Current cash: ${cash ? money(cash.shares) : 'none'}`}><input className="num" type="number" min="0" step="0.01" value={draft.amount} onChange={e => set({ amount: e.target.value })} /></Field>
      </> : <>
        <div className="wide"><div className="ad-field"><span>Funds — choose both to enter the same stock in each</span></div>
          <div className="ad-pills">{data.funds.map(f => <label key={f.name} className={'ad-pill' + (draft.legs[f.name]?.on ? ' on' : '')}><input type="checkbox" checked={!!draft.legs[f.name]?.on} onChange={e => setLeg(f.name, { on: e.target.checked })} />{f.name}</label>)}</div></div>
        {needsPosition
          ? <Field label="Position"><select value={draft.ticker} onChange={e => pickPosition(e.target.value)}>
              <option value="">Choose a position…</option>
              {[...options.values()].map(p => <option key={p.ticker} value={p.ticker}>{p.ticker} — {p.name}</option>)}
            </select></Field>
          : <Field label="Ticker"><input className="num" value={draft.ticker} maxLength={12} placeholder="NVDA" onChange={e => set({ ticker: e.target.value.toUpperCase() })} /></Field>}
        <Field label="Execution price ($)"><input className="num" type="number" min="0" step="any" value={draft.price} onChange={e => set({ price: e.target.value })} /></Field>
        {draft.kind === 'buy_new' && <>
          <Field label="Company name" hint="Only needed if the platform hasn't seen this stock before."><input value={draft.name} onChange={e => set({ name: e.target.value })} /></Field>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <Field label="Sector"><select value={draft.sector} onChange={e => set({ sector: e.target.value })}><option value="">Choose…</option>{data.sectors.map(x => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Cap class"><select value={draft.cap_class} onChange={e => set({ cap_class: e.target.value })}><option value="">Choose…</option>{data.capClasses.map(x => <option key={x}>{x}</option>)}</select></Field>
          </div>
        </>}
      </>}
    </div>

    {!isCash && activeFunds.length > 0 && <div className="ad-legs">
      {activeFunds.map(f => {
        const leg = draft.legs[f.name]
        const pos = heldIn(f, draft.ticker.trim().toUpperCase())
        const t = ticket(f, leg)
        return <div key={f.name} className="ad-leg">
          <div className="ad-leg-name">{f.name}<small>{pos ? `holds ${qty(pos.shares)} sh` : draft.kind === 'buy_new' ? 'not held yet' : ''}</small></div>
          {draft.kind === 'sell_all'
            ? <div className="ad-field"><span>Shares</span><div className="num" style={{ padding: '10px 0', fontSize: 12, color: '#9aa7c2' }}>{pos ? qty(pos.shares) : '—'}</div></div>
            : <Field label="Shares"><input className="num" type="number" min="0" step="any" value={leg.shares} onChange={e => setLeg(f.name, { shares: e.target.value })} /></Field>}
          <Field label={buying ? 'Pay for it with' : 'Put the proceeds in'}><select value={leg.route} onChange={e => setLeg(f.name, { route: e.target.value })}>{routesFor(f).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
          {t && <div className={'ad-ticket ' + t.cls} style={t.bad ? { borderLeftColor: '#ff8a8a', color: '#ffb4b4' } : undefined}>{t.text}</div>}
        </div>
      })}
    </div>}

    <div className="ad-actions">
      <span className="settings-error" role="alert">{formError}</span>
      <button type="button" className="settings-primary" onClick={addToBatch}>Add to batch</button>
    </div>

    {batch.length > 0 && <div className="ad-ledger">
      <div className="ad-ledger-head"><div className="settings-card-title">Pending changes <span className="num" style={{ color: '#6b7794', fontWeight: 400 }}>({batch.length})</span></div></div>
      {batch.map((c, i) => { const d = ledgerDetail(c); return <div key={i} className="ad-ledger-row">
        <span className={'ad-side ' + d.tag}>{d.label}</span>
        <div className="ad-ledger-main">{d.main}{d.sub && <small>{d.sub}</small>}</div>
        <div className="ad-ledger-num">{d.num}</div>
        <button type="button" className="ad-x" aria-label="Remove change" onClick={() => setBatch(b => b.filter((_, j) => j !== i))}>×</button>
      </div> })}
      <div style={{ marginTop: 14 }}><Field label="Note for the transaction log (optional)"><input value={note} maxLength={300} onChange={e => setNote(e.target.value)} /></Field></div>
      <div className="ad-actions"><button type="button" className="settings-primary" onClick={startReview}>Review {batch.length} change{batch.length === 1 ? '' : 's'}</button></div>
    </div>}
    {done && <div className="ad-done" role="status">{done}</div>}

    {review && <div className="ad-overlay" onClick={() => open && setReview(null)}>
      <div className="ad-modal" role="dialog" aria-modal="true" aria-labelledby="ad-confirm-title" onClick={e => e.stopPropagation()}>
        <div className="ad-modal-body">
          <h2 id="ad-confirm-title">Review before applying</h2>
          <div className="ad-warn"><b>This can't be undone.</b> Positions, cost basis and cash update for everyone as soon as you apply, and there is no way to reverse them from this page.</div>
          {byFund.map(([fname, ps]) => <div key={fname} className="ad-fund">
            <h3>{fname}</h3>
            {ps.map(p => {
              const cashRow = p.secType === 'cash'
              const f = cashRow ? money : qty
              const diff = p.after - p.before
              return <div key={p.ticker} className="ad-pos">
                <div className="ad-pos-name"><b>{p.ticker}</b><small>{cashRow ? 'Cash' : p.name}{p.new ? ' · new position' : ''}{p.closed ? ' · closed' : ''}{p.secType === 'etf' ? ' · index' : ''}</small></div>
                <div className="ad-pos-nums num">{f(p.before)}<span className="arrow">→</span><span style={{ color: '#e8edf7' }}>{f(p.after)}</span>{!cashRow && ' sh'}
                  <span className={'ad-delta ' + (diff >= 0 ? 'up' : 'down')}>{diff >= 0 ? '+' : '−'}{cashRow ? money(Math.abs(diff)).replace('−', '') : qty(Math.abs(diff))}</span></div>
              </div>
            })}
          </div>)}
          <ul className="ad-steps">{review.preview.changes.map((c, i) => <li key={i}><b>{c.fund} {c.ticker}</b> — {c.summary}</li>)}</ul>
        </div>
        <div className="ad-modal-foot">
          <label className="ad-ack"><input type="checkbox" checked={review.understood} onChange={e => setReview(r => ({ ...r, understood: e.target.checked }))} /> I've checked these numbers and understand they can't be reversed.</label>
          {review.error && <div className="settings-error" role="alert" style={{ marginTop: 10 }}>{review.error}</div>}
          <div className="ad-actions">
            <button type="button" className="ad-btn" disabled={review.busy} onClick={() => setReview(null)}>Keep editing</button>
            <button type="button" className="ad-btn danger" disabled={!review.understood || review.busy} onClick={apply}>{review.busy ? 'Applying…' : `Apply ${batch.length} change${batch.length === 1 ? '' : 's'}`}</button>
          </div>
        </div>
      </div>
    </div>}
  </div>
}
