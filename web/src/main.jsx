import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import { ErrorScreen } from './StatusScreens.jsx'

// A render error used to unmount the whole tree and leave a blank screen. Show a
// recoverable screen instead; "Reset view" clears the saved fund so a bad
// persisted selection cannot crash every reload.
class Boundary extends React.Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(err) { console.error('Terminal render error', err) }
  reset = () => {
    try { localStorage.removeItem('uoig.fund') } catch (_) { /* ignore */ }
    window.location.assign('/')
  }
  render() {
    if (!this.state.failed) return this.props.children
    return <ErrorScreen title="Something went wrong" message="The terminal hit an unexpected error rendering this view."
      actions={[{ label: 'Reload', onClick: () => window.location.reload(), primary: true }, { label: 'Reset view', onClick: this.reset }]} />
  }
}

createRoot(document.getElementById('root')).render(<Boundary><App /></Boundary>)
