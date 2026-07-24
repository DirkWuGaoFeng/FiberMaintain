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

export const sendChatMessage = async (message, onEvent) => {
  return new Promise((resolve, reject) => {
    const eventSource = new EventSource('/api/v1/chat?message=' + encodeURIComponent(message))
    
    eventSource.onmessage = (event) => {
      if (event.data === '[DONE]') {
        eventSource.close()
        resolve()
      } else {
        try {
          const data = JSON.parse(event.data)
          if (onEvent) onEvent(data)
        } catch (e) {
          console.error('SSE parse error:', e)
        }
      }
    }
    
    eventSource.onerror = (error) => {
      eventSource.close()
      reject(error)
    }
  })
}

export default api