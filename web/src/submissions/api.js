const BASE = import.meta.env.VITE_API_BASE || ''

async function request(path, method = 'GET', body) {
  const response = await fetch(`${BASE}/api${path}`, {
    method, credentials: 'include',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not save this item. Check the fields and try again.')
  return data
}

export const getFlags = (week = '') => request('/flags/mine' + (week ? `?week=${week}` : ''))
export const saveFlag = (body, id) => request(id ? `/flags/${id}` : '/flags', id ? 'PATCH' : 'POST', body)
export const removeFlag = id => request(`/flags/${id}`, 'DELETE')
export const submitDraft = sector => request('/submissions', 'POST', { sector })
export const getQueue = (week = '') => request('/submissions' + (week ? `?week=${week}` : ''))
export const acknowledge = id => request(`/submissions/${id}/ack`, 'POST')
export const getInbox = () => request('/inbox')
export const markRead = id => request(`/inbox/${id}/read`, 'POST')
