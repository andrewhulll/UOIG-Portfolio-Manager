import React from 'react'
import { s } from '../ui.js'
import { MarketScreener } from './MarketScreener.jsx'

export function Screener({ onOpenStock }) {
  return (
    <div style={s('display:flex;flex-direction:column;height:100%;')}>
      <div style={s('padding:16px 16px 0;')}>
        <div style={s("font:600 17px 'IBM Plex Sans';color:#e8edf7;")}>Screener</div>
      </div>
      <MarketScreener onOpenStock={onOpenStock} />
    </div>
  )
}
