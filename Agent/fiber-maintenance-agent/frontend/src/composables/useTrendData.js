import { ref } from 'vue'
import { getTrend } from '../api/index.js'

const points = ref([])
const loading = ref(false)

function pad(n) { return String(n).padStart(2, '0') }

function formatTs(date) {
  return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())} ` +
         `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

async function fetchTrend(hours = 24) {
  loading.value = true
  try {
    const now = new Date()
    const start = new Date(now.getTime() - hours * 3600000)
    const { data } = await getTrend({
      start_time: formatTs(start),
      end_time: formatTs(now),
    })
    points.value = data.points || []
  } catch (e) {
    points.value = []
  }
  loading.value = false
}

export function useTrendData() {
  return { points, loading, fetchTrend }
}
