import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1', timeout: 30000 })

export const getRealtimeStats = () => api.get('/fibers/stats/realtime')
export const getTrend = (params) => api.get('/fibers/stats/trend', { params })
export const getColored = (color) => api.get('/fibers/colored', { params: { color } })
export const getAllColoredFibers = () => api.get('/fibers/colored/all')
export const getFiberScene = (fiberId) => api.get(`/topology/fibers/${fiberId}/scene`)
export const uploadKbDoc = (formData) => api.post('/knowledge/upload', formData, {
  headers: { 'Content-Type': 'multipart/form-data' }
})
export const getKbDocs = (status) => api.get('/knowledge/docs', { params: { status } })
export const reviewKbDoc = (id, data) => api.post(`/knowledge/docs/${id}/review`, data)
export const deleteKbDoc = (id) => api.delete(`/knowledge/docs/${id}`)
export const getStatus = () => api.get('/status')

// 可观测性 API (§17.6.2 运行看板)
export const getObsMetrics = () => api.get('/observability/metrics')
export const getObsTraces = (limit = 20) => api.get('/observability/traces', { params: { limit } })
export const getObsTraceDetail = (traceId) => api.get(`/observability/traces/${traceId}`)

export const sendChatMessage = async (message, onEvent) => {
  const resp = await fetch('/api/v1/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`Chat request failed: ${resp.status}`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() // keep incomplete line in buffer
    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data: ')) continue
      const payload = trimmed.slice(6)
      if (payload === '[DONE]') return
      try {
        const data = JSON.parse(payload)
        if (onEvent) onEvent(data)
      } catch (e) {
        console.error('SSE parse error:', e)
      }
    }
  }
}

export default api