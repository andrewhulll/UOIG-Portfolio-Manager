const BASE = import.meta.env.VITE_API_BASE || ''

async function request(path, method = 'GET', body) {
  const response = await fetch(`${BASE}/api${path}`, {
    method, credentials: 'include',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Screener request failed.')
  return data
}

export const getScreenerFields = () => request('/screener/fields')
export const runScreener = (body) => request('/screener/run', 'POST', body)
