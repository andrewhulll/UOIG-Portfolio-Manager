// Shared UI helpers for the terminal.
//
// `s()` parses a design CSS string into a React style object so components can be
// written with literal CSS (the house idiom used throughout App.jsx). Colors stay
// inline hex literals per that idiom (no exported token object).

// Parse a design CSS string into a React style object (keeps styles verbatim).
export function s(css) {
  const o = {}
  String(css).split(';').forEach((d) => {
    const i = d.indexOf(':')
    if (i < 0) return
    const k = d.slice(0, i).trim()
    if (!k) return
    o[k.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = d.slice(i + 1).trim()
  })
  return o
}

// Sector accent colors — shared by My Coverage, the Inbox and anywhere else a
// sector needs a consistent chip color.
export const SECTOR_COLORS = { TMT: '#5a93f9', Consumer: '#e8674c', Financials: '#c06fd6', Financial: '#c06fd6', Healthcare: '#21d07a', IME: '#f4a531' }
