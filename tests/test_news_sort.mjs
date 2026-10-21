import assert from 'node:assert/strict'
import { sortNews } from '../web/src/news/sort.js'

const articles = [
  { id: 'older-high', publishedAt: '2026-10-01', analysis: { status: 'ready', impactConfidence: .9, impactScore: 1 } },
  { id: 'newer-high', publishedAt: '2026-10-02', analysis: { status: 'ready', impactConfidence: .9, impactScore: 2 } },
  { id: 'pending', publishedAt: '2026-10-04', analysis: { status: 'pending' } },
  { id: 'important', publishedAt: '2026-10-03', analysis: { status: 'ready', impactConfidence: .5, impactScore: 4 } },
  { id: 'no-date', analysis: { status: 'unavailable' } },
]
const ids = sort => sortNews(articles, sort).map(a => a.id)
assert.deepEqual(ids('date'), ['pending', 'important', 'newer-high', 'older-high', 'no-date'])
assert.deepEqual(ids('confidence'), ['newer-high', 'older-high', 'important', 'pending', 'no-date'])
assert.deepEqual(ids('impact'), ['important', 'newer-high', 'older-high', 'pending', 'no-date'])
assert.equal(articles[0].id, 'older-high')
console.log('News sorting checks passed')
