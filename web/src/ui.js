// Shared UI helpers for the terminal.
//
// `s()` parses a design CSS string into a React style object so components can
// be written with literal CSS (the house idiom used throughout App.jsx). `C` is
// the dark-terminal palette + UOIG brand tokens, exported so screens outside
// App.jsx (the auth flow, status screens) stay on the same colors.

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

// Terminal palette. Backgrounds go darkest -> lighter; text goes brightest ->
// dimmest. Brand green/gold are the UOIG marks, used sparingly on the auth
// brand panel; terminal blue stays the primary-action color everywhere.
export const C = {
  // backgrounds
  app: '#070a12',
  panel: '#0a0f1a',
  card: '#0e1422',
  cardAlt: '#0e1626',
  // borders
  border: '#1d2840',
  borderSoft: '#141c30',
  borderActive: '#28406e',
  // text
  text: '#e8edf7',
  text2: '#9aa7c2',
  muted: '#6b7794',
  faint: '#5d6a85',
  dim: '#3c465e',
  // accent / primary
  blue: '#2f6df6',
  blueBusy: '#2a3a5c',
  link: '#5a93f9',
  // positive
  green: '#21d07a',
  successText: '#7fe0a8',
  successBg: '#0c2a1e',
  successBorder: '#1d4536',
  // negative
  errText: '#ffb4b4',
  errIcon: '#ff8a8a',
  errBg: '#2a1115',
  errBorder: '#4a1f25',
  // UOIG brand
  brandGreen: '#004f27',
  brandGold: '#ffc000',
  gold: '#c9b56a',
}
