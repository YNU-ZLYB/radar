const BASE = ''

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail || detail } catch (e) { /* ignore */ }
    throw new Error(detail)
  }
  if (options.raw) return res
  return res.json()
}

export function get(path, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  ).toString()
  return request(qs ? `${path}?${qs}` : path)
}

export function post(path, body = {}) {
  return request(path, { method: 'POST', body: JSON.stringify(body) })
}

export const api = {
  get,
  post,
  meta: () => get('/api/v1/meta'),
  dashboard: () => get('/api/v1/dashboard'),
  varieties: () => get('/api/v1/varieties'),
  variety: (code) => get(`/api/v1/varieties/${code}`),
  feed: (params) => get('/api/v1/articles', params),
  article: (id) => get(`/api/v1/articles/${id}`),
  manual: (body) => post('/api/v1/articles/manual', body),
  feedback: (id, body) => post(`/api/v1/articles/${id}/feedback`, body),
  oil: () => get('/api/v1/market/oil'),
  digestList: () => get('/api/v1/digests'),
  digestGenerate: (date) => post(`/api/v1/digests/generate${date ? `?date=${date}` : ''}`),
  sources: () => get('/api/v1/sources'),
  toggleSource: (id) => post(`/api/v1/sources/${id}/toggle`),
  runTask: (task) => post(`/api/v1/tasks/run/${task}`),
}

export function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function fmtDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function fmtNum(v, digits = 2) {
  return v === null || v === undefined ? '—' : Number(v).toFixed(digits)
}
