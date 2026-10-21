import React from 'react'
import { getNewsAnalysis } from '../api.js'
import './news.css'
export { sortNews } from './sort.js'

const LABELS = { supports: 'Supports thesis', detracts: 'Detracts from thesis', neutral: 'Neutral', positive: 'Positive implications', negative: 'Negative implications', unclear: 'Unclear' }
const IMPACT = ['Minimal', 'Low', 'Moderate', 'High', 'Transformative']
const identity = item => item.articleKey || item.id || item.link || item.title
export function useNewsAssessments(ticker, news) {
  const [remote, setRemote] = React.useState(null)
  // Include the assessment status so a new page response resets the polling window.
  const key = JSON.stringify([ticker, news.map(n => [identity(n), n.title, n.summary, n.analysis])])
  React.useEffect(() => {
    setRemote(null)
    if (!news.some(n => n.analysis?.status === 'pending' || n.analysis?.status === 'queued')) return
    let live = true, timer, attempts = 0
    const poll = async () => {
      try {
        const result = await getNewsAnalysis(ticker)
        if (!live) return
        setRemote({ key, items: result.news || [] })
        if (++attempts < 40 && result.news?.some(n => ['pending', 'queued'].includes(n.analysis?.status))) timer = setTimeout(poll, 3000)
      } catch {
        if (live && ++attempts < 5) timer = setTimeout(poll, 5000)
      }
    }
    timer = setTimeout(poll, 1500)
    return () => { live = false; clearTimeout(timer) }
  }, [key])
  if (remote?.key !== key) return news
  const updates = new Map(remote.items.map(item => [identity(item), item]))
  return news.map(item => {
    const update = updates.get(identity(item))
    // A newer feed may have revised this article; do not attach its assessment to old text.
    return update && update.title === item.title && update.summary === item.summary ? { ...item, analysis: update.analysis } : item
  })
}

export function NewsAssessment({ analysis }) {
  if (!analysis || analysis.status === 'disabled') return null
  if (analysis.status !== 'ready') return <div className="news-assessment news-assessment-muted" role="status">{['pending', 'queued'].includes(analysis.status) ? 'Assessing news…' : 'Assessment unavailable'}</div>
  const uncertain = analysis.classification === 'unclear'
  const impact = IMPACT[Math.max(0, Math.min(4, Math.round(analysis.impactScore)))]
  return <div className="news-assessment">
    <span className={`news-tag ${analysis.classification}`} title={`Jev assessment${analysis.thesisDate ? ` against thesis dated ${analysis.thesisDate}` : ''}. Classification confidence: ${Math.round(analysis.classificationConfidence * 100)}%.`}>{LABELS[analysis.classification] || 'Unclear'}</span>
    <span className="news-tag" title="Estimated business significance over the next twelve months; not a predicted stock-price move.">Impact: {uncertain && analysis.basis === 'headline' ? 'Uncertain' : impact}</span>
    <span className="news-confidence" title="Jev's certainty in its impact assessment. This is not the probability of a price move or a guarantee of correctness.">Confidence: {Math.round(analysis.impactConfidence * 100)}%</span>
    {analysis.basis === 'headline' && <span className="news-assessment-muted">Headline only</span>}
  </div>
}

export function NewsSort({ value, onChange }) {
  return <label className="news-sort">Sort by <select aria-label="Sort news" value={value} onChange={e => onChange(e.target.value)} onClick={e => e.stopPropagation()}>
    <option value="date">Date · newest first</option>
    <option value="confidence">Confidence · highest first</option>
    <option value="impact">Impact · highest first</option>
  </select></label>
}
