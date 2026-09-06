// Thin client for the FastAPI backend.
// Same-origin by default (single-container deploy); set VITE_API_BASE to point at
// a remote backend (e.g. the Vercel frontend talking to the Render backend).
// credentials:'include' sends the session cookie on every call — required when the
// frontend and backend are on different origins (and harmless same-origin).
const BASE = import.meta.env.VITE_API_BASE || ''
const j = async (r) => {
  if (!r.ok) {
    let detail = ''
    try {
      const body = await r.json()
      detail = body?.detail || body?.message || ''
    } catch (_) {
      // Some proxy/platform failures return HTML or an empty body.
    }
    const error = new Error(detail ? `${r.status}: ${detail}` : String(r.status))
    error.status = r.status
    error.detail = detail
    throw error
  }
  return r.json()
}
const get = (path) => fetch(`${BASE}${path}`, { credentials: 'include' }).then(j)
const post = (path, body) =>
  fetch(`${BASE}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then(j)

export const getData = () => get('/api/data')
export const getSeries = (ticker, period) =>
  get(`/api/series/${encodeURIComponent(ticker)}?period=${period}`)
export const getFundSeries = (fund, period) =>
  get(`/api/fund-series/${fund}?period=${period}`)
export const getSectorSeries = (group, period = '1M') =>
  get(`/api/sector-series/${encodeURIComponent(group)}?period=${period}`)
export const getStock = (ticker) => get(`/api/stock/${encodeURIComponent(ticker)}`)
export const searchTickers = (q) => get(`/api/search?q=${encodeURIComponent(q)}`)
export const getQuote = (ticker) => get(`/api/quote/${encodeURIComponent(ticker)}`)
export const getHolders = (ticker) => get(`/api/holders/${encodeURIComponent(ticker)}`)
export const getOptimizeDiagnostics = (fund) => get(`/api/optimize/diagnostics/${encodeURIComponent(fund)}`)
export const getOptimizeWhatif = (fund) => get(`/api/optimize/whatif/${encodeURIComponent(fund)}`)
export const postOptimizeSolve = (fund, body) => post(`/api/optimize/solve/${encodeURIComponent(fund)}`, body)
export const getPredictions = (ticker) => get(`/api/predictions/${encodeURIComponent(ticker)}`)
export const getThesis = (ticker) => get(`/api/thesis/${encodeURIComponent(ticker)}`)
export const postChat = (messages, context) => post('/api/chat', { messages, context })
export const runAgent = (task) => post('/api/agent/run', { task })
export const getAgentRun = (jobId) => get(`/api/agent/run/${jobId}`)

// ---- auth (WorkOS) ----
// The login redirect is a full navigation (Google consent can't be fetched).
export const getMe = () => get('/api/auth/me')
export const logout = () => post('/api/auth/logout')
// Pass an invitation token to carry it through Google OAuth (invitee accept flow).
export const loginUrl = (invitationToken) =>
  `${BASE}/api/auth/login${invitationToken ? `?invitation_token=${encodeURIComponent(invitationToken)}` : ''}`
export const sendInvite = (email, roleSlug) => post('/api/auth/invite', { email, role_slug: roleSlug })
// Invitee accept flow: look up an invitation by token; set a password to accept.
export const getInvitation = (token) => get(`/api/auth/invitation?token=${encodeURIComponent(token)}`)
export const acceptPassword = (body) => post('/api/auth/accept-password', body)
export const passwordLogin = (email, password) => post('/api/auth/password-login', { email, password })
export const requestPasswordReset = (email) => post('/api/auth/password-reset', { email })
export const confirmPasswordReset = (token, password) => post('/api/auth/password-reset/confirm', { token, password })
export const verifyEmail = (code, pendingToken) => post('/api/auth/verify-email', { code, pendingToken })
