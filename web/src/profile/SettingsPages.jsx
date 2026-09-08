import React from 'react'
import { getOrganizationMembers, sendInvite, updateProfile, updateMemberCoverage, updateMemberRole } from '../api.js'
import { s } from '../ui.js'
import './settings.css'

const ROLE_COLORS = { admin: '#f4a531', 'sector-leader': '#c06fd6', member: '#5a93f9' }
const SECTOR_COLORS = { TMT: '#5a93f9', Consumer: '#e8674c', Financials: '#c06fd6', Financial: '#c06fd6', Healthcare: '#21d07a', IME: '#f4a531' }
const COVERAGE_SECTORS = ['TMT', 'Consumer', 'Financials', 'Healthcare', 'IME']
const ROLE_OPTIONS = [['member', 'Analyst'], ['sector-leader', 'Sector Leader'], ['admin', 'Admin']]

function initials(name) {
  const parts = String(name || 'UO').trim().split(/\s+/)
  return ((parts[0]?.[0] || 'U') + (parts.length > 1 ? parts[parts.length - 1][0] : parts[0]?.[1] || 'O')).toUpperCase()
}

function Avatar({ member, size = 44 }) {
  if (member.profilePictureUrl) return <img className="settings-avatar" src={member.profilePictureUrl} alt="" style={{ width: size, height: size }} />
  return <div className="settings-avatar settings-avatar-fallback" style={{ width: size, height: size, fontSize: Math.round(size * .29) }}>{initials(member.name)}</div>
}

function RoleBadge({ role, label }) {
  const color = ROLE_COLORS[role] || '#9aa7c2'
  return <span className="settings-badge" style={{ color, borderColor: color + '55', background: color + '12' }}>{label || role}</span>
}

function RoleEditor({ member, auth, onChanged }) {
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState('')
  const isSelf = member.id === auth.user?.id
  const change = async (e) => {
    const role = e.target.value
    setBusy(true); setError('')
    try { await updateMemberRole(member.id, role); await onChanged() }
    catch (err) { setError(err.detail || 'Could not update role') }
    finally { setBusy(false) }
  }
  return <div>
    <select className="role-select" value={member.role} disabled={busy || isSelf} onChange={change}>
      {ROLE_OPTIONS.map(([slug, label]) => <option key={slug} value={slug}>{label}</option>)}
    </select>
    {isSelf && <div className="settings-muted">You can't change your own role</div>}
    {error && <div className="settings-error">{error}</div>}
  </div>
}

function CoverageEditor({ member, holdings, onOpenStock, onChanged }) {
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState('')
  const [ticker, setTicker] = React.useState('')
  const [sector, setSector] = React.useState(COVERAGE_SECTORS[0])
  const options = React.useMemo(() => {
    const seen = new Map()
    holdings.forEach(h => { if (!seen.has(h.t)) seen.set(h.t, h) })
    return Array.from(seen.values()).sort((a, b) => a.t.localeCompare(b.t))
  }, [holdings])
  const save = async (next) => {
    setBusy(true); setError('')
    try { await updateMemberCoverage(member.id, next); await onChanged() }
    catch (err) { setError(err.detail || 'Could not save coverage') }
    finally { setBusy(false) }
  }
  const add = () => { if (ticker) { save([...member.coverage, { sector, ticker }]); setTicker('') } }
  const remove = (c) => save(member.coverage.filter(x => !(x.sector === c.sector && x.ticker === c.ticker)))
  return <>
    <div className="coverage-list">
      {member.coverage.length ? member.coverage.map(c => (
        <div className="coverage-edit-row" key={c.sector + c.ticker}>
          <button onClick={() => onOpenStock(c.ticker)}><span>{c.ticker}</span><small>{c.sector}</small><b>↗</b></button>
          <button className="coverage-remove" disabled={busy} aria-label={`Remove ${c.ticker}`} onClick={() => remove(c)}>×</button>
        </div>
      )) : <small className="settings-muted">No coverage assigned</small>}
    </div>
    <div className="coverage-add-row">
      <select value={sector} disabled={busy} onChange={e => setSector(e.target.value)}>{COVERAGE_SECTORS.map(x => <option key={x}>{x}</option>)}</select>
      <select value={ticker} disabled={busy} onChange={e => setTicker(e.target.value)}>
        <option value="">Choose a holding…</option>
        {options.map(h => <option key={h.t} value={h.t}>{h.t} — {h.n}</option>)}
      </select>
      <button className="settings-primary" disabled={busy || !ticker} onClick={add}>Add</button>
    </div>
    {error && <div className="settings-error">{error}</div>}
  </>
}

function SettingsShell({ active, onNavigate, eyebrow, title, subtitle, children }) {
  const tabs = [['profile', 'My profile'], ['preferences', 'Preferences'], ['organization', 'Organization']]
  return <div className="settings-page">
    <div className="settings-hero">
      <div className="settings-eyebrow">{eyebrow}</div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
    <div className="settings-layout">
      <nav className="settings-side" aria-label="Settings">
        <div className="settings-side-label">Settings</div>
        {tabs.map(([key, label]) => <button key={key} className={active === key ? 'active' : ''} onClick={() => onNavigate(key)}>{label}<span>›</span></button>)}
      </nav>
      <section className="settings-content">{children}</section>
    </div>
  </div>
}

export function ProfilePage({ auth, onNavigate, onUserUpdated }) {
  const user = auth.user || {}
  const [firstName, setFirst] = React.useState(user.firstName || '')
  const [lastName, setLast] = React.useState(user.lastName || '')
  const [status, setStatus] = React.useState('idle')
  const save = async (e) => {
    e.preventDefault(); setStatus('saving')
    try {
      const result = await updateProfile({ firstName, lastName })
      onUserUpdated(result.user); setStatus('saved')
    } catch (err) { setStatus(err.detail || 'Could not save profile') }
  }
  return <SettingsShell active="profile" onNavigate={onNavigate} eyebrow="Account" title="Your profile" subtitle="The identity teammates see across the UOIG terminal.">
    <div className="settings-card profile-summary">
      <Avatar member={{ ...user, name: user.name || user.email }} size={64} />
      <div><div className="settings-card-title">{user.name || user.email}</div><div className="settings-muted">{user.email}</div></div>
      <RoleBadge role={auth.role} label={auth.role === 'member' ? 'Analyst' : auth.role === 'sector-leader' ? 'Sector Leader' : 'Admin'} />
    </div>
    <form className="settings-card" onSubmit={save}>
      <div className="settings-section-head"><div><div className="settings-card-title">Personal information</div><div className="settings-muted">Used in the member directory and assignment views.</div></div></div>
      <div className="settings-fields two">
        <label>First name<input value={firstName} maxLength={60} onChange={e => { setFirst(e.target.value); setStatus('idle') }} /></label>
        <label>Last name<input value={lastName} maxLength={60} onChange={e => { setLast(e.target.value); setStatus('idle') }} /></label>
        <label className="wide">Email<input value={user.email || ''} disabled /><small>Managed by your sign-in provider.</small></label>
      </div>
      <div className="settings-actions">
        <span className={status === 'saved' ? 'settings-success' : 'settings-error'}>{status === 'saved' ? 'Profile saved' : (!['idle', 'saving'].includes(status) ? status : '')}</span>
        <button className="settings-primary" disabled={status === 'saving' || !firstName.trim()}>{status === 'saving' ? 'Saving…' : 'Save changes'}</button>
      </div>
    </form>
    <div className="settings-card settings-info-row"><div><div className="settings-card-title">Profile photo</div><div className="settings-muted">Your photo comes from the account you use to sign in. Initials appear when no photo is available.</div></div><span className="settings-lock">Provider managed</span></div>
  </SettingsShell>
}

function readPrefs() {
  try { return JSON.parse(localStorage.getItem('uoig.preferences') || '{}') } catch (_) { return {} }
}

export function PreferencesPage({ fundOptions, currentFund, currentPeriod, onNavigate, onApply }) {
  const existing = readPrefs()
  const [prefs, setPrefs] = React.useState({
    defaultFund: existing.defaultFund || currentFund || 'all', defaultPeriod: existing.defaultPeriod || currentPeriod || 'YTD',
    landingPage: existing.landingPage || 'dashboard', density: existing.density || 'comfortable', reducedMotion: existing.reducedMotion ?? false,
  })
  const [saved, setSaved] = React.useState(false)
  const field = (key, value) => { setPrefs(p => ({ ...p, [key]: value })); setSaved(false) }
  const save = () => { localStorage.setItem('uoig.preferences', JSON.stringify(prefs)); localStorage.setItem('uoig.fund', prefs.defaultFund); onApply(prefs); setSaved(true) }
  return <SettingsShell active="preferences" onNavigate={onNavigate} eyebrow="Workspace" title="Terminal preferences" subtitle="Choose how the terminal opens and how much information it shows.">
    <div className="settings-card">
      <div className="settings-section-head"><div><div className="settings-card-title">Startup view</div><div className="settings-muted">Applied when you return to the terminal on this browser.</div></div></div>
      <div className="settings-fields two">
        <label>Default fund<select value={prefs.defaultFund} onChange={e => field('defaultFund', e.target.value)}>{fundOptions.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}</select></label>
        <label>Default chart period<select value={prefs.defaultPeriod} onChange={e => field('defaultPeriod', e.target.value)}>{['1M','3M','6M','YTD','1Y','5Y'].map(x => <option key={x}>{x}</option>)}</select></label>
        <label>Landing page<select value={prefs.landingPage} onChange={e => field('landingPage', e.target.value)}><option value="dashboard">Funds dashboard</option><option value="stocks">Stocks</option><option value="sectors">Sectors</option><option value="optimize">Optimize</option></select></label>
        <label>Information density<select value={prefs.density} onChange={e => field('density', e.target.value)}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label>
      </div>
    </div>
    <div className="settings-card settings-toggle-row">
      <div><div className="settings-card-title">Reduce motion</div><div className="settings-muted">Turn off pulsing status indicators and interface animation.</div></div>
      <button type="button" role="switch" aria-checked={prefs.reducedMotion} className={'settings-switch ' + (prefs.reducedMotion ? 'on' : '')} onClick={() => field('reducedMotion', !prefs.reducedMotion)}><span /></button>
    </div>
    <div className="settings-actions standalone"><span className="settings-success">{saved ? 'Preferences saved' : ''}</span><button className="settings-primary" onClick={save}>Save preferences</button></div>
  </SettingsShell>
}

export function OrganizationPage({ auth, holdings, onNavigate, onOpenStock }) {
  const [data, setData] = React.useState(null)
  const [error, setError] = React.useState('')
  const [query, setQuery] = React.useState('')
  const [sector, setSector] = React.useState('All sectors')
  const [selected, setSelected] = React.useState(null)
  const [invite, setInvite] = React.useState({ email: '', role: 'member', status: 'idle', message: '' })
  const load = React.useCallback(() => getOrganizationMembers().then(x => { setData(x); setSelected(s => s || x.members[0] || null) }).catch(e => setError(e.detail || 'Could not load members')), [])
  React.useEffect(() => { load() }, [load])
  const send = async (e) => {
    e.preventDefault(); if (!invite.email.trim()) return
    setInvite(x => ({ ...x, status: 'sending', message: '' }))
    try { await sendInvite(invite.email.trim(), invite.role); setInvite({ ...invite, email: '', status: 'sent', message: `Invitation sent to ${invite.email.trim()}` }) }
    catch (err) { setInvite(x => ({ ...x, status: 'error', message: err.detail || 'Could not send invitation' })) }
  }
  if (error) return <SettingsShell active="organization" onNavigate={onNavigate} eyebrow="UOIG" title="Organization" subtitle="Member directory and coverage ownership."><div className="settings-card settings-empty"><b>Directory unavailable</b><span>{error}</span><button onClick={() => { setError(''); load() }}>Try again</button></div></SettingsShell>
  if (!data) return <SettingsShell active="organization" onNavigate={onNavigate} eyebrow="UOIG" title="Organization" subtitle="Member directory and coverage ownership."><div className="settings-card settings-empty"><span className="settings-spinner" />Loading members…</div></SettingsShell>
  const sectors = ['All sectors', ...Array.from(new Set(data.members.flatMap(m => m.sectors))).sort()]
  const needle = query.trim().toLowerCase()
  const members = data.members.filter(m => (sector === 'All sectors' || m.sectors.includes(sector)) && (!needle || [m.name, m.email, m.roleName, ...m.sectors, ...m.coverage.map(c => c.ticker)].join(' ').toLowerCase().includes(needle)))
  const detail = members.find(m => m.id === selected?.id) || members[0] || null
  return <SettingsShell active="organization" onNavigate={onNavigate} eyebrow={data.organization.name} title="Member directory" subtitle="Find teammates by sector, role, or company coverage.">
    <div className="settings-stats"><div><strong>{data.members.length}</strong><span>Active members</span></div><div><strong>{data.members.filter(m => m.role === 'sector-leader').length}</strong><span>Sector leaders</span></div><div><strong>{new Set(data.members.flatMap(m => m.coverage.map(c => c.ticker))).size}</strong><span>Companies covered</span></div></div>
    {auth.canInvite && <form className="settings-card invite-row" onSubmit={send}>
      <div><div className="settings-card-title">Invite a teammate</div><div className="settings-muted">Add an active UOIG member with the right access level.</div></div>
      <input type="email" required placeholder="name@uoregon.edu" value={invite.email} onChange={e => setInvite({ ...invite, email: e.target.value, status: 'idle', message: '' })} />
      <select value={invite.role} onChange={e => setInvite({ ...invite, role: e.target.value })}><option value="member">Analyst</option><option value="sector-leader">Sector Leader</option></select>
      <button className="settings-primary" disabled={invite.status === 'sending'}>{invite.status === 'sending' ? 'Sending…' : 'Send invite'}</button>
      {invite.message && <div className={invite.status === 'sent' ? 'settings-success invite-message' : 'settings-error invite-message'}>{invite.message}</div>}
    </form>}
    <div className="directory-toolbar"><div className="directory-search"><span>⌕</span><input aria-label="Search members" placeholder="Search members, sectors, or tickers" value={query} onChange={e => setQuery(e.target.value)} /></div><select aria-label="Filter by sector" value={sector} onChange={e => setSector(e.target.value)}>{sectors.map(x => <option key={x}>{x}</option>)}</select><span className="settings-muted">{members.length} shown</span></div>
    <div className="directory-grid">
      <div className="member-list">
        <div className="member-list-head"><span>Member</span><span>Team & coverage</span><span>Role</span></div>
        {members.map(member => <button key={member.id} className={'member-row ' + (detail?.id === member.id ? 'selected' : '')} onClick={() => setSelected(member)}>
          <span className="member-identity"><Avatar member={member} /><span><b>{member.name}</b><small>{member.email}</small></span>{member.isMock && <em>Mock</em>}</span>
          <span className="member-coverage"><span>{member.sectors.length ? member.sectors.join(' · ') : 'Leadership'}</span><small>{member.coverage.length ? member.coverage.map(c => c.ticker).join(', ') : 'No company assignments'}</small></span>
          <RoleBadge role={member.role} label={member.roleName} />
        </button>)}
        {!members.length && <div className="settings-empty">No members match these filters.</div>}
      </div>
      <aside className="member-detail">
        {detail && <><div className="member-detail-top"><Avatar member={detail} size={56} /><div><h2>{detail.name}</h2><p>{detail.email}</p></div></div>
          {auth.canInvite ? <RoleEditor key={detail.id} member={detail} auth={auth} onChanged={load} /> : <RoleBadge role={detail.role} label={detail.roleName} />}
          <div className="member-detail-label">Sector teams</div><div className="chip-wrap">{detail.sectors.length ? detail.sectors.map(x => <span key={x} style={{ borderColor: (SECTOR_COLORS[x] || '#6b7794') + '55', color: SECTOR_COLORS[x] || '#9aa7c2' }}>{x}</span>) : <small className="settings-muted">No sector assigned</small>}</div>
          <div className="member-detail-label">Company coverage</div>
          {auth.canInvite
            ? <CoverageEditor key={detail.id} member={detail} holdings={holdings} onOpenStock={onOpenStock} onChanged={load} />
            : <div className="coverage-list">{detail.coverage.length ? detail.coverage.map(c => <button key={c.sector + c.ticker} onClick={() => onOpenStock(c.ticker)}><span>{c.ticker}</span><small>{c.sector}</small><b>↗</b></button>) : <small className="settings-muted">No company assignments</small>}</div>}
        </>}
      </aside>
    </div>
  </SettingsShell>
}
