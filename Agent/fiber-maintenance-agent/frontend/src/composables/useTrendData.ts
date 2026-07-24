import { ref } from 'vue'
import axios from 'axios'

const REST_URL = import.meta.env.VITE_FIBER_REST_URL || ''

export interface TrendPoint {
  timestamp: string
  red_count: number
  yellow_count: number
  total_colored: number
}

function formatTS(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
    ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds())
}

export function useTrendData() {
  const points = ref<TrendPoint[]>([])
  const loading = ref(false)

  async function fetchTrend(hours: number = 24) {
    loading.value = true
    try {
      const end = new Date()
      const start = new Date(end.getTime() - hours * 3600_000)
      const { data } = await axios.get(`${REST_URL}/api/v1/fibers/stats/trend`, {
        params: {
          start_time: formatTS(start),
          end_time: formatTS(end),
        },
      })
      points.value = data.points || []
    } catch {
      points.value = []
    } finally {
      loading.value = false
    }
  }

  return { points, loading, fetchTrend }
}