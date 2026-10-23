import React from 'react'
import { submitFeedback } from '../api.js'
import { s } from '../ui.js'

export function FeedbackButton({ view }) {
  const [open, setOpen] = React.useState(false)
  const [text, setText] = React.useState('')
  const [status, setStatus] = React.useState('idle')  // idle | sending | sent | error message
  const close = () => { setOpen(false); setStatus('idle') }
  const send = async (e) => {
    e.preventDefault()
    if (!text.trim()) return
    setStatus('sending')
    try {
      await submitFeedback(text.trim(), window.location.pathname)
      setText(''); setStatus('sent')
    } catch (err) { setStatus(err.detail || 'Could not send feedback. Try again.') }
  }
  const busy = status === 'sending'
  const error = !['idle', 'sending', 'sent'].includes(status) ? status : ''
  return <>
    <button onClick={() => setOpen(true)} className="dc-hover no-print" style={s("border:1px solid #25324d;background:transparent;color:#9aa7c2;border-radius:7px;padding:6px 11px;cursor:pointer;font:500 11px 'IBM Plex Sans';white-space:nowrap;")}>Submit feedback</button>
    {open && <div onClick={close} style={s('position:fixed;inset:0;z-index:200;background:rgba(5,8,14,.6);display:flex;align-items:center;justify-content:center;padding:16px;')}>
      <form onClick={(e) => e.stopPropagation()} onSubmit={send} style={s('width:min(460px,100%);background:#0e1422;border:1px solid #1d2840;border-radius:12px;padding:20px;box-shadow:0 20px 56px rgba(0,0,0,.6);')}>
        {status === 'sent' ? <>
          <div style={s("font:600 14px 'IBM Plex Sans';color:#e8edf7;")}>Thanks — feedback sent</div>
          <div style={s("font:400 11.5px 'IBM Plex Sans';color:#8290ad;margin-top:8px;")}>The admins will see it on their Admin page.</div>
          <div style={s('display:flex;justify-content:flex-end;gap:8px;margin-top:18px;')}><button type="button" onClick={close} className="settings-primary">Close</button></div>
        </> : <>
          <div style={s("font:600 14px 'IBM Plex Sans';color:#e8edf7;")}>Submit feedback</div>
          <div style={s("font:400 11.5px 'IBM Plex Sans';color:#8290ad;margin:6px 0 12px;")}>Bug, idea, or something confusing? Tell us what would make the platform better.</div>
          <textarea autoFocus value={text} maxLength={4000} onChange={(e) => { setText(e.target.value); setStatus('idle') }} placeholder="Type your feedback…" rows={6}
            style={s("width:100%;box-sizing:border-box;resize:vertical;background:#090e18;border:1px solid #25324d;color:#e8edf7;border-radius:8px;padding:10px 11px;outline:none;font:400 12px 'IBM Plex Sans';")} />
          {error && <div className="settings-error" style={s('margin-top:8px;')}>{error}</div>}
          <div style={s('display:flex;justify-content:flex-end;gap:8px;margin-top:14px;')}>
            <button type="button" onClick={close} style={s("border:1px solid #2b3b5d;background:#13203a;color:#cdd6e8;border-radius:8px;padding:9px 14px;cursor:pointer;font:500 10.5px 'IBM Plex Sans';")}>Cancel</button>
            <button className="settings-primary" disabled={busy || !text.trim()}>{busy ? 'Sending…' : 'Send feedback'}</button>
          </div>
        </>}
      </form>
    </div>}
  </>
}
