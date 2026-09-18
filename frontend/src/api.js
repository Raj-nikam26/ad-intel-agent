const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export { API_BASE }

// Set by the Clerk wrapper when sign-in is on; returns a fresh session token.
let tokenGetter = null
export function setTokenGetter(fn) { tokenGetter = fn }

async function authHeaders() {
  const token = tokenGetter ? await tokenGetter() : null
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function req(path, options) {
  const headers = { ...(options?.headers || {}), ...(await authHeaders()) }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    let detail
    try {
      detail = (await res.json()).detail
    } catch {
      detail = res.statusText
    }
    throw new Error(detail || `Request failed (${res.status})`)
  }
  return res.json()
}

const qs = (params) => {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === '' || v === false) continue
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export const api = {
  health: () => req('/health'),


  upload(file) {
    const body = new FormData()
    body.append('file', file)
    return req('/upload', { method: 'POST', body })
  },

  sample: () => req('/sample', { method: 'POST' }),

  session: (sessionId) => req(`/session/${sessionId}`),

  mapping: (sessionId) => req(`/mapping/${sessionId}`),

  setMapping(sessionId, body) {
    return req(`/mapping/${sessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  },

  data(sessionId, params = {}) {
    return req(`/data/${sessionId}${qs(params)}`)
  },

  issues(sessionId, params = {}) {
    return req(`/issues/${sessionId}${qs(params)}`)
  },

  graphStats(sessionId) {
    return req(`/graph/${sessionId}/stats`)
  },

  graphSearch(sessionId, q) {
    return req(`/graph/${sessionId}/search${qs({ q })}`)
  },

  graphNeighborhood(sessionId, node, depth = 1, maxNodes = 60) {
    return req(`/graph/${sessionId}/neighborhood${qs({ node, depth, max_nodes: maxNodes })}`)
  },

  diff(sessionId, version) {
    return req(`/diff/${sessionId}/${version}`)
  },

  chat(sessionId, message) {
    return req('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message }),
    })
  },

  history(sessionId) {
    return req(`/history/${sessionId}`)
  },

  revert(sessionId, toVersion) {
    return req('/revert', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, to_version: toVersion }),
    })
  },

  addColumn(sessionId, { name, value, sourceColumn, afterColumn }) {
    return req('/columns', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        name,
        value: value || null,
        source_column: sourceColumn || null,
        after_column: afterColumn || null,
      }),
    })
  },

  // A plain link cannot carry the Authorization header, so the file is
  // fetched and handed to the browser as a download.
  async exportFile(sessionId, filename) {
    const res = await fetch(`${API_BASE}/export/${sessionId}`, { headers: await authHeaders() })
    if (!res.ok) throw new Error(`Export failed (${res.status})`)
    const url = URL.createObjectURL(await res.blob())
    const a = Object.assign(document.createElement('a'), { href: url, download: filename })
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  },
}
