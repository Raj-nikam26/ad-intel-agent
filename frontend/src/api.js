const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export { API_BASE }

async function req(path, options) {
  const res = await fetch(`${API_BASE}${path}`, options)
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

  exportUrl(sessionId) {
    return `${API_BASE}/export/${sessionId}`
  },
}
