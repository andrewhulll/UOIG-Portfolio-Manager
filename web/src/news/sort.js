const timestamp = item => Date.parse(item.publishedAt) || 0

export function sortNews(items, sort) {
  return [...items].sort((a, b) => {
    if (sort !== 'date') {
      const field = sort === 'confidence' ? 'impactConfidence' : 'impactScore'
      const score = item => item.analysis?.status === 'ready' && Number.isFinite(item.analysis[field]) ? item.analysis[field] : -1
      const delta = score(b) - score(a)
      if (delta) return delta
    }
    return timestamp(b) - timestamp(a)
  })
}
