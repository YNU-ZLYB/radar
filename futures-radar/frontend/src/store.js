import { reactive } from 'vue'

export const live = reactive({
  connected: false,
  version: 0,
  lastEvent: null,
  toasts: [],
})

let source = null

export function pushToast(message, type = 'info') {
  const id = Date.now() + Math.random()
  live.toasts.push({ id, message, type })
  setTimeout(() => {
    const idx = live.toasts.findIndex((t) => t.id === id)
    if (idx >= 0) live.toasts.splice(idx, 1)
  }, 4500)
}

export function connectSSE() {
  if (source) return
  source = new EventSource('/api/v1/stream')
  source.onopen = () => { live.connected = true }
  source.onerror = () => { live.connected = false }
  const bump = (event, payload) => {
    live.lastEvent = { event, payload, at: Date.now() }
    live.version += 1
  }
  source.addEventListener('article_new', (e) => {
    const payload = JSON.parse(e.data)
    bump('article_new', payload)
    if (payload.data?.title) pushToast(`新资讯：${payload.data.title.slice(0, 42)}`, 'bull')
  })
  source.addEventListener('analysis_update', (e) => {
    bump('analysis_update', JSON.parse(e.data))
  })
  source.addEventListener('oil_update', (e) => {
    bump('oil_update', JSON.parse(e.data))
  })
  source.addEventListener('system', (e) => {
    bump('system', JSON.parse(e.data))
  })
}
