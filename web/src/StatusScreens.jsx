import { s } from './ui.js'

// Full-screen app-level states, shared by App.jsx (auth-loading, terminal-loading,
// data-load failure) and reusable by the auth flow. All sit on the same radial
// terminal ground and IBM Plex type as the sign-in screen.

const GROUND = "height:100vh;width:100%;display:flex;align-items:center;justify-content:center;background:radial-gradient(1200px 600px at 50% -10%,#0d1426,#070a12 60%);color:#e8edf7;font-family:'IBM Plex Sans',sans-serif;"

function Eyebrow() {
  return (
    <div style={s('display:flex;align-items:center;gap:11px;')}>
      <img src="/uoig-logo.png" alt="UOIG" style={s('width:34px;height:34px;object-fit:contain;background:#fff;border-radius:8px;padding:4px;')} />
      <div style={s("font:500 11px 'IBM Plex Mono';color:#6b7794;letter-spacing:.2em;text-transform:uppercase;")}>Investment Terminal</div>
    </div>
  )
}

// A quiet, centered wait state. `label` says what we're waiting on.
export function LoadingScreen({ label = 'Loading…' }) {
  return (
    <div style={s(GROUND)}>
      <div style={s('display:flex;flex-direction:column;align-items:center;gap:16px;')}>
        <Eyebrow />
        <div style={s('display:flex;align-items:center;gap:9px;')}>
          <span style={{ ...s('width:8px;height:8px;border-radius:50%;background:#2f6df6;'), animation: 'pulseDot 1.4s infinite' }}></span>
          <span style={s("font:500 12px 'IBM Plex Mono';color:#6b7794;letter-spacing:.06em;")}>{label}</span>
        </div>
      </div>
    </div>
  )
}

const alertIcon = (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#ff8a8a" strokeWidth="1.8"><path d="M12 3 2.5 20h19z" strokeLinejoin="round"/><path d="M12 10v4M12 17v.5" strokeLinecap="round"/></svg>
)
const linkIcon = (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#ff8a8a" strokeWidth="1.8"><path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5z"/><path d="M5 6.5 12 12l7-5.5" strokeLinecap="round"/><path d="m15.5 15.5 4 4M19.5 15.5l-4 4" strokeLinecap="round"/></svg>
)

// Shared centered error/not-found card. `actions`: [{label, onClick, primary}].
function MessageCard({ icon, title, message, actions = [], footer }) {
  return (
    <div style={s(GROUND)}>
      <div style={s('width:440px;max-width:calc(100% - 48px);display:flex;flex-direction:column;align-items:center;text-align:center;gap:22px;')}>
        <Eyebrow />
        <div style={s('width:100%;background:#0e1422;border:1px solid #1d2840;border-radius:14px;padding:32px 28px;display:flex;flex-direction:column;align-items:center;gap:18px;box-shadow:0 24px 64px rgba(0,0,0,.5);')}>
          <div style={s('width:54px;height:54px;border-radius:14px;background:#241318;border:1px solid #4a1f25;display:flex;align-items:center;justify-content:center;')}>{icon}</div>
          <div style={s('display:flex;flex-direction:column;gap:9px;')}>
            <div style={s("font:600 19px 'IBM Plex Sans';color:#e8edf7;")}>{title}</div>
            <div style={s("font:400 13px/1.6 'IBM Plex Sans';color:#9aa7c2;")}>{message}</div>
          </div>
          {actions.length > 0 && (
            <div style={s('width:100%;display:flex;flex-direction:column;gap:10px;')}>
              {actions.map((a, i) => (
                <div key={i} onClick={a.onClick} className="dc-hover"
                  style={a.primary
                    ? s('display:flex;align-items:center;justify-content:center;gap:8px;background:#2f6df6;color:#fff;border-radius:10px;padding:12px;font:600 13px \'IBM Plex Sans\';cursor:pointer;')
                    : s('display:flex;align-items:center;justify-content:center;background:transparent;color:#9aa7c2;border:1px solid #1d2840;border-radius:10px;padding:12px;font:600 13px \'IBM Plex Sans\';cursor:pointer;')}>
                  {a.label}
                </div>
              ))}
            </div>
          )}
        </div>
        {footer && <div style={s("font:400 11px 'IBM Plex Mono';color:#3c465e;")}>{footer}</div>}
      </div>
    </div>
  )
}

// Post-auth failure (e.g. the terminal data load failed). Give recovery actions.
export function ErrorScreen({ title = 'Something went wrong', message, actions, footer, kind = 'alert' }) {
  return <MessageCard icon={kind === 'link' ? linkIcon : alertIcon} title={title} message={message} actions={actions} footer={footer} />
}

// Invalid / expired link or unknown deep-link state.
export function NotFoundScreen({ title = 'Invalid or expired link', message = 'This link is invalid or has expired. If you were invited, ask your PM to resend the invitation.', actionLabel = 'Go to sign in', onAction }) {
  return <MessageCard icon={linkIcon} title={title} message={message} actions={onAction ? [{ label: actionLabel, onClick: onAction, primary: true }] : []} />
}
