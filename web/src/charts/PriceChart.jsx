import React from 'react'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export function fmtChartDate(d) {
  if (!d) return ''
  const p = String(d).split('-')
  if (p.length < 3) return String(d)
  return MONTHS[(+p[1]) - 1] + ' ' + (+p[2]) + ', ' + p[0]
}
// Catmull-Rom -> cubic Bézier: turns a list of [x,y] points into a smooth path.
// Shared by every chart in the terminal so they all curve the same way.
export function smoothPath(pts) {
  if (pts.length < 3) return pts.map((p, i) => (i ? 'L' : 'M') + p[0] + ',' + p[1]).join(' ')
  const f = 0.16  // smoothing strength (≈1/6 = classic Catmull-Rom)
  let d = 'M' + pts[0][0] + ',' + pts[0][1]
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2
    const c1x = p1[0] + (p2[0] - p0[0]) * f, c1y = p1[1] + (p2[1] - p0[1]) * f
    const c2x = p2[0] - (p3[0] - p1[0]) * f, c2y = p2[1] - (p3[1] - p1[1]) * f
    d += ' C' + c1x.toFixed(2) + ',' + c1y.toFixed(2) + ' ' + c2x.toFixed(2) + ',' + c2y.toFixed(2) + ' ' + p2[0] + ',' + p2[1]
  }
  return d
}

// Interactive single-line price chart with a price axis and a hover readout.
// Used on the stock page, and (at a smaller height) in the weekly submission editor.
export function PriceChart({ dates, values, color, height }) {
  const [hover, setHover] = React.useState(null)
  const wrapRef = React.useRef(null)
  const n = values ? values.length : 0
  if (!n) return React.createElement('div', { style: { height: height + 'px' } })

  const W = 900, padT = 6, padB = 6, plotH = height - padT - padB
  const min = Math.min.apply(null, values)
  const max = Math.max.apply(null, values)
  const span = (max - min) || 1
  const Y = (v) => +(height - padB - ((v - min) / span) * plotH).toFixed(2)
  const X = (i) => +((i / ((n - 1) || 1)) * W).toFixed(2)
  const xPct = (i) => (i / ((n - 1) || 1)) * 100

  const line = smoothPath(values.map((v, i) => [X(i), Y(v)]))
  const area = line + ' L' + W + ',' + height + ' L0,' + height + ' Z'
  const gid = 'pc-grad-' + (color || '').replace('#', '')

  const TN = 4
  const ticks = []
  for (let k = 0; k <= TN; k++) {
    const val = min + (span * k) / TN
    ticks.push({ val, y: Y(val) })
  }

  const onMove = (e) => {
    const r = wrapRef.current && wrapRef.current.getBoundingClientRect()
    if (!r || !r.width) return
    let idx = Math.round(((e.clientX - r.left) / r.width) * (n - 1))
    idx = Math.max(0, Math.min(n - 1, idx))
    setHover(idx)
  }

  const fmtPrice = (v) => '$' + v.toFixed(2)
  const gridY = (f) => +(padT + plotH * f).toFixed(1)

  const svg = React.createElement('svg', {
    key: 'svg',
    viewBox: '0 0 ' + W + ' ' + height, preserveAspectRatio: 'none',
    style: { width: '100%', height: '100%', display: 'block' },
  }, [
    React.createElement('defs', { key: 'defs' }, [
      React.createElement('linearGradient', { key: 'g', id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, [
        React.createElement('stop', { key: 'a', offset: '0', style: { stopColor: color, stopOpacity: 0.26 } }),
        React.createElement('stop', { key: 'b', offset: '1', style: { stopColor: color, stopOpacity: 0 } }),
      ]),
    ]),
  ].concat(ticks.map((t, i) => React.createElement('line', {
    key: 'grid' + i, x1: 0, y1: t.y, x2: W, y2: t.y, style: { stroke: '#16203a', strokeWidth: 1 },
  }))).concat([
    React.createElement('path', { key: 'area', d: area, style: { fill: 'url(#' + gid + ')', stroke: 'none' } }),
    React.createElement('path', { key: 'line', d: line, style: { fill: 'none', stroke: color, strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' } }),
  ]))

  // axis gutter: price labels aligned to the grid lines
  const axis = React.createElement('div', {
    key: 'axis',
    style: { position: 'relative', width: '52px', flex: '0 0 auto', height: height + 'px' },
  }, ticks.map((t, i) => React.createElement('span', {
    key: 'ax' + i,
    style: {
      position: 'absolute', right: 0, top: t.y + 'px', transform: 'translateY(-50%)',
      fontFamily: "'IBM Plex Mono'", fontSize: '9.5px', color: '#6b7794', whiteSpace: 'nowrap',
    },
  }, fmtPrice(t.val))))

  // hover overlay: crosshair, marker dot, and a price/date tooltip
  let overlay = []
  if (hover != null && hover < n) {
    const left = xPct(hover)
    const topY = Y(values[hover])
    const clamped = Math.max(11, Math.min(89, left))
    overlay = [
      React.createElement('div', {
        key: 'cross',
        style: { position: 'absolute', top: 0, bottom: 0, left: left + '%', width: '1px', background: 'rgba(154,167,194,.35)', pointerEvents: 'none' },
      }),
      React.createElement('div', {
        key: 'dot',
        style: { position: 'absolute', left: left + '%', top: topY + 'px', width: '8px', height: '8px', borderRadius: '50%', background: color, border: '2px solid #0e1422', transform: 'translate(-50%,-50%)', pointerEvents: 'none' },
      }),
      React.createElement('div', {
        key: 'tip',
        style: { position: 'absolute', left: clamped + '%', top: Math.max(0, topY - 50) + 'px', transform: 'translateX(-50%)', background: '#0a0f1a', border: '1px solid #24345a', borderRadius: '6px', padding: '5px 9px', pointerEvents: 'none', whiteSpace: 'nowrap', boxShadow: '0 4px 14px rgba(0,0,0,.45)' },
      }, [
        React.createElement('div', { key: 'p', style: { fontFamily: "'IBM Plex Mono'", fontSize: '12px', color: '#e8edf7' } }, fmtPrice(values[hover])),
        React.createElement('div', { key: 'd', style: { fontFamily: "'IBM Plex Mono'", fontSize: '9.5px', color: '#7e8aa6', marginTop: '2px' } }, fmtChartDate(dates && dates[hover])),
      ]),
    ]
  }

  const plot = React.createElement('div', {
    key: 'plot', ref: wrapRef, onMouseMove: onMove, onMouseLeave: () => setHover(null),
    style: { position: 'relative', flex: '1 1 auto', minWidth: 0, height: height + 'px', cursor: 'crosshair' },
  }, [svg].concat(overlay))

  return React.createElement('div', { style: { display: 'flex', alignItems: 'stretch', height: height + 'px' } }, [plot, axis])
}
