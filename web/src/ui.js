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
