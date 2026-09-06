import React from 'react'
import { s } from '../ui.js'
import { ErrorScreen } from '../StatusScreens.jsx'
import { loginUrl, passwordLogin, requestPasswordReset, confirmPasswordReset,
         verifyEmail, getInvitation, acceptPassword, getMe } from '../api.js'

// Redesigned, self-contained auth surface. App.jsx renders <AuthScreen> whenever
// the viewer is not signed in; on any successful sign-in this calls getMe() and
// hands the session up via props.onAuthenticated(me). All network calls reuse
// web/src/api.js unchanged.
//
// Layout: a two-column split (branded left panel + form card) that collapses to
// a single centered card below 880px. One `signMode` state machine drives the
// body: signin | accept | forgot | reset | verify, plus a fatal full-screen
// error for unknown OAuth failures.

const MIN_PW = 10  // keep in step with the WorkOS password policy (min 10)

const googleBtn = (token) => (
  <a href={loginUrl(token)} className="dc-hover" style={s("display:flex;align-items:center;justify-content:center;gap:10px;text-decoration:none;background:#fff;color:#1a1a1a;border-radius:10px;padding:12px;font:600 13px 'IBM Plex Sans';cursor:pointer;")}>
    <svg width="17" height="17" viewBox="0 0 18 18"><path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"/><path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z"/><path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33z"/><path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z"/></svg>
    Continue with Google
  </a>
)

const orRule = (
  <div style={s('display:flex;align-items:center;gap:10px;')}>
    <div style={s('flex:1;height:1px;background:#1d2840;')}></div>
    <span style={s("font:500 9.5px 'IBM Plex Sans';letter-spacing:.08em;text-transform:uppercase;color:#3c465e;")}>or</span>
    <div style={s('flex:1;height:1px;background:#1d2840;')}></div>
  </div>
)

function BrandPanel({ tagline }) {
  return (
    <div style={s("position:relative;width:46%;max-width:660px;min-width:420px;overflow:hidden;background:radial-gradient(900px 520px at 12% -5%, #0f1a2e 0%, #0a1120 46%, #070a12 100%);display:flex;flex-direction:column;justify-content:space-between;padding:56px 52px;border-right:1px solid #141c30;")}>
      <div style={s('position:absolute;inset:0;background-image:linear-gradient(#0e1626 1px,transparent 1px),linear-gradient(90deg,#0e1626 1px,transparent 1px);background-size:46px 46px;opacity:.45;')}></div>
      <div style={s('position:absolute;top:-130px;left:-90px;width:440px;height:440px;border-radius:50%;background:radial-gradient(circle,rgba(0,79,39,.55) 0%,rgba(0,79,39,0) 70%);')}></div>
      <div style={s('position:absolute;bottom:-150px;right:-70px;width:380px;height:380px;border-radius:50%;background:radial-gradient(circle,rgba(255,192,0,.13) 0%,rgba(255,192,0,0) 70%);')}></div>
      <div style={s('position:relative;display:flex;align-items:center;gap:13px;')}>
        <img src="/uoig-logo.png" alt="UOIG" style={s('width:46px;height:46px;object-fit:contain;background:#fff;border-radius:10px;padding:5px;')} />
        <div style={s('display:flex;flex-direction:column;gap:3px;')}>
          <div style={s("font:600 15px 'IBM Plex Sans';color:#e8edf7;")}>University of Oregon Investment Group</div>
          <div style={s("font:500 10px 'IBM Plex Mono';color:#8a97b4;letter-spacing:.22em;text-transform:uppercase;")}>Investment Terminal</div>
        </div>
      </div>
      <div style={s('position:relative;display:flex;flex-direction:column;gap:26px;')}>
        <svg width="380" height="118" viewBox="0 0 380 118" fill="none" style={{ opacity: .95, maxWidth: '100%' }}>
          <defs><linearGradient id="uoigCurve" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#21d07a"/><stop offset="1" stopColor="#21d07a" stopOpacity="0"/></linearGradient></defs>
          <polyline points="0,96 42,88 84,92 126,68 168,74 210,48 252,58 294,30 336,22 380,6 380,118 0,118" fill="url(#uoigCurve)" opacity=".16"/>
          <polyline points="0,96 42,88 84,92 126,68 168,74 210,48 252,58 294,30 336,22 380,6" stroke="#21d07a" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <div style={s("font:400 15px/1.65 'IBM Plex Sans';color:#9aa7c2;max-width:400px;")}>{tagline}</div>
      </div>
      <div style={s('position:relative;display:flex;align-items:center;justify-content:space-between;')}>
        <div style={s("font:500 11px 'IBM Plex Mono';color:#5d6a85;letter-spacing:.13em;")}>TALL FIRS · ALUMNI FUND</div>
        <div style={s('display:flex;align-items:center;gap:6px;background:#0e1626;border:1px solid #1d2840;border-radius:20px;padding:5px 11px;')}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#ffc000" strokeWidth="2"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>
          <span style={s("font:600 9px 'IBM Plex Sans';letter-spacing:.09em;text-transform:uppercase;color:#c9b56a;")}>Invite-only</span>
        </div>
      </div>
    </div>
  )
}

export default class AuthScreen extends React.Component {
  constructor(props) {
    super(props)
    this.state = {
      mode: 'signin', busy: false, msg: '', ok: '',
      email: '', pass: '', pass2: '', code: '', first: '', last: '',
      resetToken: null, pendingToken: null, inviteToken: null, inviteInfo: null,
      fatal: null, narrow: false,
    }
  }

  componentDidMount() {
    try {
      this._mq = window.matchMedia('(max-width: 720px)')
      this.setState({ narrow: this._mq.matches })
      this._onMq = (e) => this.setState({ narrow: e.matches })
      if (this._mq.addEventListener) this._mq.addEventListener('change', this._onMq)
      else this._mq.addListener(this._onMq)
    } catch (e) { /* no matchMedia (SSR/old): stay wide */ }

    let authErr = null, resetToken = null, inviteToken = null
    try {
      const p = new URLSearchParams(window.location.search)
      authErr = p.get('auth_error')
      if (p.get('reset') && p.get('token')) resetToken = p.get('token')
      inviteToken = p.get('invitation_token')
      if (authErr || resetToken || inviteToken) window.history.replaceState({}, '', window.location.pathname)
    } catch (e) { /* ignore */ }

    const next = {}
    if (inviteToken) { next.mode = 'accept'; next.inviteToken = inviteToken }
    else if (resetToken) { next.mode = 'reset'; next.resetToken = resetToken }
    else if (authErr === 'not_invited') { next.mode = 'signin'; next.msg = this._notInvitedMsg() }
    else if (authErr === 'bad_state' || authErr === 'auth_failed') { next.mode = 'signin'; next.msg = "Sign-in didn't complete. Please try again." }
    else if (authErr) { next.fatal = { title: 'Sign-in error', message: 'Something went wrong signing you in. Head back and try again.' } }

    this.setState(next, () => { if (inviteToken) this._loadInvitation(inviteToken) })
  }

  componentWillUnmount() {
    try {
      if (!this._mq) return
      if (this._mq.removeEventListener) this._mq.removeEventListener('change', this._onMq)
      else this._mq.removeListener(this._onMq)
    } catch (e) { /* ignore */ }
  }

  _notInvitedMsg() {
    return "That account isn't on the invite list. Access is invite-only — ask your PM to send an invitation, then use the invited email or Google account."
  }

  _set = (patch) => this.setState(patch)
  _go = (mode) => this.setState({ mode, msg: '', ok: '' })

  _afterLogin = () => {
    getMe()
      .then((me) => this.props.onAuthenticated(me))
      .catch(() => this.setState({ busy: false, msg: 'Signed in, but the session could not be loaded. Please try again.' }))
  }

  _loadInvitation = (token) => {
    this.setState({ inviteInfo: 'loading' })
    getInvitation(token)
      .then((inv) => this.setState({ inviteInfo: inv }))
      .catch(() => this.setState({ inviteInfo: 'invalid' }))
  }

  _passwordLogin = () => {
    const { email, pass } = this.state
    if (!email || !pass) { this.setState({ msg: 'Enter your email and password.' }); return }
    this.setState({ busy: true, msg: '', ok: '' })
    passwordLogin(email, pass)
      .then((r) => { if (r && r.needsVerification) this.setState({ busy: false, mode: 'verify', pendingToken: r.pendingToken, msg: '', ok: '' }); else this._afterLogin() })
      .catch((e) => this.setState({ busy: false, msg: this._loginErr(e) }))
  }
  _loginErr(e) {
    const c = String(e)
    if (c.includes('401')) return 'Invalid email or password.'
    if (c.includes('403')) return this._notInvitedMsg()
    if (c.includes('503')) return "Email + password sign-in isn't enabled yet. Try Google, or contact your PM."
    return 'Sign-in failed. Please try again.'
  }

  _requestReset = () => {
    const { email } = this.state
    if (!email) { this.setState({ msg: 'Enter your email.' }); return }
    this.setState({ busy: true, msg: '', ok: '' })
    const done = () => this.setState({ busy: false, ok: 'If that email has an account, a reset link is on its way. Check your inbox.' })
    requestPasswordReset(email).then(done).catch(done) // always neutral — never reveal account existence
  }

  _confirmReset = () => {
    const { pass, pass2, resetToken } = this.state
    if (pass.length < MIN_PW) { this.setState({ msg: `Use at least ${MIN_PW} characters.` }); return }
    if (pass !== pass2) { this.setState({ msg: "Passwords don't match." }); return }
    this.setState({ busy: true, msg: '', ok: '' })
    confirmPasswordReset(resetToken, pass)
      .then(() => this.setState({ busy: false, mode: 'signin', pass: '', pass2: '', ok: 'Password set. Sign in with your new password.' }))
      .catch((e) => this.setState({ busy: false, msg: this._resetErr(e) }))
  }
  _resetErr(e) {
    // 422 = WorkOS rejected the password against the org policy (too short, low
    // complexity, or breached); 400 = the reset link itself is bad/expired.
    if (e?.status === 422) return e.detail || "That password doesn't meet the requirements — try a longer, less common one."
    if (e?.status === 400 || String(e).includes('400')) return 'That reset link is invalid or has expired. Request a new one.'
    return 'Could not set your password. Please try again.'
  }

  _verifyEmail = () => {
    const { code, pendingToken } = this.state
    if (!code) { this.setState({ msg: 'Enter the code we emailed you.' }); return }
    this.setState({ busy: true, msg: '', ok: '' })
    verifyEmail(code, pendingToken)
      .then(() => this._afterLogin())
      .catch((e) => this.setState({ busy: false, msg: String(e).includes('401') ? 'That code is invalid or has expired.' : 'Verification failed. Please try again.' }))
  }

  _acceptPassword = () => {
    const { pass, pass2, first, last, inviteToken } = this.state
    if (pass.length < MIN_PW) { this.setState({ msg: `Use at least ${MIN_PW} characters.` }); return }
    if (pass !== pass2) { this.setState({ msg: "Passwords don't match." }); return }
    this.setState({ busy: true, msg: '', ok: '' })
    acceptPassword({ invitationToken: inviteToken, password: pass, firstName: first || undefined, lastName: last || undefined })
      .then((r) => { if (r && r.needsVerification) this.setState({ busy: false, mode: 'verify', pendingToken: r.pendingToken }); else this._afterLogin() })
      .catch((e) => this.setState({ busy: false, msg: this._acceptErr(e) }))
  }
  _acceptErr(e) {
    if (e?.status === 409) return e.detail || 'That account already exists. Use Forgot / set password, then reopen this invitation.'
    // 422 = WorkOS rejected the *password* against the org policy (too common, or
    // found in a breach — neither of which we can check client-side).
    if (e?.status === 422) return e.detail || "That password doesn't meet the requirements — try a longer, less common one."
    if (e?.status === 400) return e.detail || 'WorkOS rejected the account details. Check the password requirements and try again.'
    if (e?.status === 503) return 'Password sign-up is temporarily unavailable. Try again shortly or use Google.'
    const c = String(e)
    if (c.includes('409')) return 'An account already exists for this invite. Sign in below, or continue with Google.'
    if (c.includes('401')) return 'Could not sign you in after creating the account. Try signing in below.'
    if (c.includes('404')) return 'This invitation could not be found. Ask your PM to resend it.'
    return 'Could not create your account. Please try again.'
  }

  // ---- presentational helpers ----
  _field = (label, key, type, onEnter, opts = {}) => (
    <div style={s('display:flex;flex-direction:column;gap:6px;')}>
      <div style={s("font:600 8.5px 'IBM Plex Sans';letter-spacing:.07em;text-transform:uppercase;color:#6b7794;")}>{label}</div>
      <input
        type={type} value={this.state[key]} placeholder={opts.placeholder || ''}
        autoComplete={opts.autoComplete || (type === 'password' ? 'current-password' : 'on')}
        onChange={(e) => this.setState({ [key]: e.target.value })}
        onKeyDown={(e) => { if (e.key === 'Enter' && onEnter) onEnter() }}
        style={s("width:100%;box-sizing:border-box;background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:12px 13px;color:#e8edf7;outline:none;font:400 13px 'IBM Plex Sans';")} />
      {opts.hint && <div style={s("font:400 10px 'IBM Plex Sans';color:#5d6a85;")}>{opts.hint}</div>}
    </div>
  )

  // Live checklist mirroring the WorkOS "Strong" password policy. The length rule
  // is deterministic so we check it as the user types; complexity (zxcvbn ≥ 3) and
  // breach (haveibeenpwned) are enforced by WorkOS on submit and shown here so the
  // requirements are no surprise.
  _pwPolicy = () => {
    const pw = this.state.pass || ''
    const rule = (met, live, text) => {
      const color = live ? (met ? '#7fe0a8' : '#6b7794') : '#9aa7c2'
      const mark = live ? (met ? '✓' : '○') : '•'
      return (
        <div style={{ ...s("display:flex;align-items:center;gap:8px;font:400 10.5px/1.5 'IBM Plex Sans';"), color }}>
          <span style={s('width:11px;text-align:center;flex:none;')}>{mark}</span>
          <span>{text}</span>
        </div>
      )
    }
    return (
      <div style={s('display:flex;flex-direction:column;gap:3px;background:#0e1422;border:1px solid #1d2840;border-radius:9px;padding:10px 12px;')}>
        {rule(pw.length >= MIN_PW, true, `At least ${MIN_PW} characters`)}
        {rule(false, false, 'Not a common or easily guessed password')}
        {rule(false, false, 'Not found in a known data breach')}
      </div>
    )
  }

  _primary = (label, onClick) => (
    <div onClick={this.state.busy ? undefined : onClick} className="dc-hover"
      style={{ ...s("display:flex;align-items:center;justify-content:center;border-radius:10px;padding:12px;font:600 13px 'IBM Plex Sans';cursor:pointer;color:#fff;"), background: this.state.busy ? '#2a3a5c' : '#2f6df6' }}>
      {this.state.busy ? '…' : label}
    </div>
  )

  _link = (label, onClick) => (
    <div onClick={onClick} style={s("font:500 11.5px 'IBM Plex Sans';color:#5a93f9;cursor:pointer;text-align:center;")}>{label}</div>
  )

  _banners() {
    const { msg, ok } = this.state
    return (
      <>
        {msg && <div style={s("display:flex;align-items:flex-start;gap:10px;font:400 11.5px/1.55 'IBM Plex Sans';color:#ffb4b4;background:#2a1115;border:1px solid #4a1f25;border-radius:9px;padding:11px 13px;")}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#ff8a8a" strokeWidth="2" style={{ flex: '0 0 auto', marginTop: 1 }}><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.5" strokeLinecap="round"/></svg>
          <span>{msg}</span>
        </div>}
        {ok && <div style={s("font:400 11.5px/1.55 'IBM Plex Sans';color:#7fe0a8;background:#0c2a1e;border:1px solid #1d4536;border-radius:9px;padding:11px 13px;")}>{ok}</div>}
      </>
    )
  }

  // In-panel message for invite problems (invalid / accepted / revoked / expired).
  _inviteMessage(title, message) {
    return (
      <div style={s('display:flex;flex-direction:column;align-items:center;text-align:center;gap:20px;')}>
        <div style={s('width:52px;height:52px;border-radius:13px;background:#241318;border:1px solid #4a1f25;display:flex;align-items:center;justify-content:center;')}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ff8a8a" strokeWidth="1.8"><path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5z"/><path d="M5 6.5 12 12l7-5.5" strokeLinecap="round"/><path d="m15.5 15.5 4 4M19.5 15.5l-4 4" strokeLinecap="round"/></svg>
        </div>
        <div style={s('display:flex;flex-direction:column;gap:9px;')}>
          <div style={s("font:600 20px 'IBM Plex Sans';color:#e8edf7;")}>{title}</div>
          <div style={s("font:400 13px/1.6 'IBM Plex Sans';color:#9aa7c2;")}>{message}</div>
        </div>
        {this._primary('Go to sign in', () => this._go('signin'))}
      </div>
    )
  }

  // Build the form body + heading/sub/tagline for the current mode.
  _content() {
    const { mode } = this.state
    if (mode === 'forgot') {
      return {
        heading: 'Reset your password', sub: "We'll email you a link to set a new one.",
        tagline: 'Locked out? Reset takes a minute. This same link is how invited teammates set their first password.',
        body: (<>
          {this._banners()}
          {this._field('Email', 'email', 'email', this._requestReset, { placeholder: 'you@uoregon.edu', autoComplete: 'email' })}
          {this._primary('Send reset link', this._requestReset)}
          {this._link('‹ Back to sign in', () => this._go('signin'))}
        </>),
      }
    }
    if (mode === 'reset') {
      return {
        heading: 'Set a new password', sub: 'Choose a new password for your account.',
        tagline: "Almost there. Choose a strong password and you'll be back on the desk.",
        body: (<>
          {this._banners()}
          {this._field('New password', 'pass', 'password', this._confirmReset, { autoComplete: 'new-password', placeholder: `At least ${MIN_PW} characters` })}
          {this._pwPolicy()}
          {this._field('Confirm password', 'pass2', 'password', this._confirmReset, { autoComplete: 'new-password' })}
          {this._primary('Set password', this._confirmReset)}
          {this._link('‹ Back to sign in', () => this._go('signin'))}
        </>),
      }
    }
    if (mode === 'verify') {
      return {
        heading: 'Verify your email', sub: 'Enter the 6-digit code we emailed you.',
        tagline: "One quick check that this inbox is yours, and you're in.",
        body: (<>
          {this._banners()}
          {this._field('Verification code', 'code', 'text', this._verifyEmail, { placeholder: '6-digit code', autoComplete: 'one-time-code' })}
          {this._primary('Verify', this._verifyEmail)}
          {this._link('‹ Back to sign in', () => this._go('signin'))}
        </>),
      }
    }
    if (mode === 'accept') {
      const info = this.state.inviteInfo
      const tagline = "You've been invited to the endowment desk. Set up your account once — then it's live prices, P&L, risk and research in a single terminal."
      if (info === 'loading' || info == null) {
        return { heading: null, tagline, body: (<div style={s("font:400 12px 'IBM Plex Sans';color:#6b7794;text-align:center;padding:8px 0;")}>Checking your invitation…</div>) }
      }
      if (info === 'invalid') {
        return { heading: null, tagline, body: this._inviteMessage('Invalid or expired link', 'This invitation link is invalid or could not be found. If you were invited, ask your PM to resend it.') }
      }
      if (!info.pending) {
        const m = info.state === 'accepted' ? ['Invitation already accepted', 'This invitation was already accepted — just sign in.']
          : info.state === 'revoked' ? ['Invitation revoked', 'This invitation was revoked. Ask your PM to send a new one.']
          : ['This invitation has expired', 'Invitation links are time-limited for security. Ask your PM to send a fresh invite.']
        return { heading: null, tagline, body: this._inviteMessage(m[0], m[1]) }
      }
      return {
        heading: 'Create your account',
        sub: (<>Invited as <span style={s('color:#e8edf7;')}>{info.email}</span>. Set a password to finish — or continue with Google.</>),
        tagline,
        body: (<>
          {this._banners()}
          <div style={s('display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px;')}>
            {this._field('First name', 'first', 'text', this._acceptPassword, { placeholder: 'Optional', autoComplete: 'given-name' })}
            {this._field('Last name', 'last', 'text', this._acceptPassword, { placeholder: 'Optional', autoComplete: 'family-name' })}
          </div>
          {this._field('Create password', 'pass', 'password', this._acceptPassword, { autoComplete: 'new-password', placeholder: `At least ${MIN_PW} characters` })}
          {this._pwPolicy()}
          {this._field('Confirm password', 'pass2', 'password', this._acceptPassword, { autoComplete: 'new-password' })}
          {this._primary('Accept & enter', this._acceptPassword)}
          {orRule}
          {googleBtn(this.state.inviteToken)}
        </>),
      }
    }
    // signin (default)
    return {
      heading: 'Sign in', sub: 'Welcome back to the Investment Terminal.',
      tagline: (<>A Bloomberg-grade view of the <span style={s('color:#e8edf7;')}>Tall Firs</span> and <span style={s('color:#e8edf7;')}>Alumni Fund</span> endowment portfolios — live prices, P&L, risk and research in a single terminal.</>),
      body: (<>
        {this._banners()}
        {this._field('Email', 'email', 'email', this._passwordLogin, { placeholder: 'you@uoregon.edu', autoComplete: 'email' })}
        {this._field('Password', 'pass', 'password', this._passwordLogin, { autoComplete: 'current-password' })}
        {this._primary('Sign in', this._passwordLogin)}
        {this._link('Forgot / set password', () => this._go('forgot'))}
        {orRule}
        {googleBtn()}
        <div style={s("font:400 11px/1.5 'IBM Plex Sans';color:#5d6a85;text-align:center;")}>Access is invite-only — use the email or Google account that received your invitation.</div>
      </>),
    }
  }

  render() {
    if (this.state.fatal) {
      return <ErrorScreen title={this.state.fatal.title} message={this.state.fatal.message}
        actions={[{ label: 'Back to sign in', onClick: () => this.setState({ fatal: null, mode: 'signin' }), primary: true }]} />
    }
    const { heading, sub, tagline, body } = this._content()
    const card = (
      <div style={s('display:flex;flex-direction:column;gap:20px;')}>
        {(heading || sub) && (
          <div style={s('display:flex;flex-direction:column;gap:7px;')}>
            {heading && <div style={s("font:600 22px 'IBM Plex Sans';color:#e8edf7;")}>{heading}</div>}
            {sub && <div style={s("font:400 13px/1.55 'IBM Plex Sans';color:#9aa7c2;")}>{sub}</div>}
          </div>
        )}
        {body}
      </div>
    )

    // Desktop-only product: on phones / very narrow windows, show a notice rather
    // than a cramped sign-in form (the terminal itself needs the screen real estate).
    if (this.state.narrow) {
      return (
        <div style={s("min-height:100vh;width:100%;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:20px;background:radial-gradient(600px 400px at 50% -8%, #0f1a2e, #070a12 62%);color:#e8edf7;font-family:'IBM Plex Sans',sans-serif;padding:32px 24px;text-align:center;")}>
          <img src="/uoig-logo.png" alt="UOIG" style={s('width:54px;height:54px;object-fit:contain;background:#fff;border-radius:12px;padding:6px;')} />
          <div style={s('display:flex;flex-direction:column;gap:9px;align-items:center;')}>
            <div style={s("font:600 17px 'IBM Plex Sans';color:#e8edf7;")}>Investment Terminal</div>
            <div style={s("font:400 13px/1.6 'IBM Plex Sans';color:#9aa7c2;max-width:300px;")}>The Investment Terminal is built for the desktop. Please open it on a larger screen to sign in.</div>
          </div>
          <div style={s("font:500 10px 'IBM Plex Mono';color:#5d6a85;letter-spacing:.12em;text-transform:uppercase;")}>Tall Firs · Alumni Fund</div>
        </div>
      )
    }

    return (
      <div style={s("height:100vh;width:100%;display:flex;background:#070a12;color:#e8edf7;font-family:'IBM Plex Sans',sans-serif;overflow:hidden;")}>
        <BrandPanel tagline={tagline} />
        <div style={s('flex:1;display:flex;align-items:center;justify-content:center;background:#0a0f1a;padding:40px;overflow-y:auto;')}>
          <div style={s('width:100%;max-width:380px;')}>{card}</div>
        </div>
      </div>
    )
  }
}
