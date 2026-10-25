import React from 'react'
import { useStatements } from './StatementsPanel.jsx'
import { ConsensusPanel } from './ConsensusPanel.jsx'
import './financials.css'

function Notice({ title, body, action }) {
  return (
    <section className="fin-panel" aria-label="Analyst consensus">
      <div className="fin-notice">
        <div className="fin-notice-title">{title}</div>
        <div className="fin-notice-body">{body}</div>
        {action}
      </div>
    </section>
  )
}

// The Research tab: analyst consensus, estimates, targets and broker actions.
// Shares its fetch (and cache) with the Financials tab, so switching between them is free.
export function ResearchPanel({ ticker }) {
  const [state, reload] = useStatements(ticker)
  if (state.status === 'loading') return <Notice title="Loading analyst research" body="Pulling estimates, price targets and broker actions from Yahoo Finance." />
  if (state.status === 'pending') return <Notice title="Research isn't ready yet" body="This holding's analyst data is filled in by the nightly refresh. Run the refresh once and it will appear here." />
  if (state.status === 'error') {
    return <Notice title="Couldn't load analyst research" body="The backend may be offline or Yahoo rate-limited the request."
      action={<button type="button" className="fin-btn" onClick={reload}>Try again</button>} />
  }
  return <ConsensusPanel consensus={state.data.consensus} currency={state.data.currency} />
}
