// Run: node tests/test_financials_format.mjs
import assert from 'node:assert/strict'
import { fmtValue, fmtPercent, yoy, pctOfBase, sparkPoints, autoUnit, toCsv,
  fmtRatio, fmtCompact, valuationCells, trackPos, upside, revisionChange, gradeText, targetText,
  ratingLabel, ratingOrder, filterBroker } from '../web/src/financials/format.js'

const money = { key: 'revenue', kind: 'flow', level: 0 }
assert.equal(fmtValue(416161000000, money, 'B'), '416.16')
assert.equal(fmtValue(-1500000, money, 'M'), '(1.5)')
assert.equal(fmtValue(null, money, 'M'), '—')
assert.equal(fmtValue(7.46, { key: 'dilutedEps', kind: 'eps' }, 'B'), '7.46')
assert.equal(fmtValue(15000000000, { key: 'dilutedShares', kind: 'stock' }, 'B'), '15,000.0')

assert.equal(fmtPercent(0.1234), '12.3%')
assert.equal(fmtPercent(-0.05), '(5.0%)')
assert.equal(fmtPercent(null), '—')

// newest-first: [2025, 2024, 2023]; annual lag 1
assert.equal(yoy([110, 100, 80], 0, 1), 0.1)
assert.equal(yoy([110, 100, 80], 2, 1), null)       // no prior year
assert.equal(yoy([110, 0, 80], 0, 1), null)         // zero base
assert.equal(yoy([10, -5], 0, 1), 'n/m')            // negative base
assert.equal(yoy([5, 1, 1, 1, 4], 0, 4), 0.25)      // quarterly lag
assert.equal(pctOfBase(25, 100), 0.25)
assert.equal(pctOfBase(25, 0), null)

const pts = sparkPoints([30, 20, 10]) // newest-first: rising over time
assert.equal(pts.length, 3)
assert.ok(pts[0][0] < pts[2][0], 'oldest point is leftmost')
assert.ok(pts[2][1] < pts[0][1], 'higher value is drawn higher (smaller y)')
assert.equal(sparkPoints([1, 2]), null)
assert.equal(sparkPoints([1, null, 3, null]), null)

assert.equal(autoUnit([{ key: 'revenue', kind: 'flow', level: 0, vals: [4e11, 3e11] }]), 'B')
assert.equal(autoUnit([{ key: 'revenue', kind: 'flow', level: 0, vals: [3e8] }]), 'M')

assert.equal(
  toCsv(['FY2025', 'FY2024'], [{ key: 'revenue', label: 'Total, revenue', vals: [2, null] }], { period: 'TTM', vals: { revenue: 5 } }),
  'Line item,FY2025,FY2024,TTM\n"Total, revenue",2,,5')

// ratios / valuation
assert.equal(fmtRatio(0.469, 'pct'), '46.9%')
assert.equal(fmtRatio(1.338, 'x'), '1.34x')
assert.equal(fmtRatio(-2.59, 'x'), '(2.59x)')
assert.equal(fmtRatio(null, 'x'), '—')
assert.equal(fmtCompact(5.07e12), '5.07T')
assert.equal(fmtCompact(4.162e11), '416.2B')
assert.equal(fmtCompact(3.25e7), '32.5M')
const cells = valuationCells({ marketCap: 5.07e12, trailingPE: 39.9, dividendYield: 0.31, beta: null })
assert.deepEqual(cells.map((c) => c.text), ['5.07T', '39.9x', '0.31%'])
assert.deepEqual(valuationCells(null), [])

// consensus helpers
assert.equal(trackPos(50, 0, 100), 50)
assert.equal(trackPos(150, 0, 100), 100)
assert.equal(trackPos(5, 10, 10), null)
assert.ok(Math.abs(upside(120, 100) - 0.2) < 1e-9)
assert.equal(upside(120, 0), null)
assert.ok(Math.abs(revisionChange({ current: 2.1, d90: 1.8 }) - 1 / 6) < 1e-9)
assert.ok(revisionChange({ current: -1, d90: -2 }) > 0, 'a smaller loss is an upward revision')
assert.equal(revisionChange({ current: 2, d90: 0 }), null)
assert.equal(gradeText({ from: 'Buy', to: 'Hold' }), 'Buy → Hold')
assert.equal(gradeText({ from: 'Neutral', to: 'Neutral' }), 'Neutral')
assert.equal(targetText({ target: 283, priorTarget: 304 }), '304.00 → 283.00')
assert.equal(targetText({ target: 100, priorTarget: 100 }), '100.00')
assert.equal(targetText({ target: null }), '—')
assert.equal(ratingLabel('0m'), 'Now')
assert.equal(ratingLabel('-2m'), '2 mo ago')
assert.deepEqual(ratingOrder([{ period: '0m' }, { period: '-1m' }]).map((r) => r.period), ['-1m', '0m'])
const log = [{ firm: 'JP Morgan', action: 'main' }, { firm: 'Loop Capital', action: 'down' }]
assert.equal(filterBroker(log, { firm: 'loop' }).length, 1)
assert.equal(filterBroker(log, { action: 'main' })[0].firm, 'JP Morgan')
assert.equal(filterBroker(log).length, 2)
console.log('financials format: ok')
