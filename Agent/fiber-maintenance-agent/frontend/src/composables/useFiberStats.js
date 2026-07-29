import { ref, onMounted, onUnmounted } from 'vue'
import { getRealtimeStats } from '../api/index.js'

const stats = ref({
  red_count: 0,
  yellow_count: 0,
  green_count: 0,
  total_colored: 0,
  active_alarms: 0,
})
const recentChanges = ref([])
const wsConnected = ref(false)
let ws = null
let timer = null

function connectWs() {
  try {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    ws = new WebSocket(`${proto}//${location.host}/ws/v1/events`)
    ws.onopen = () => { wsConnected.value = true }
    ws.onclose = () => {
      wsConnected.value = false
      setTimeout(connectWs, 3000)
    }
    ws.onerror = () => { wsConnected.value = false }
    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
        if (data.type === 'color_change') {
          recentChanges.value.unshift({
            fiber_id: data.fiber_id,
            old_color: data.old_color?.toLowerCase(),
            new_color: data.new_color?.toLowerCase(),
            timestamp: new Date().toISOString(),
          })
          if (recentChanges.value.length > 50) recentChanges.value.pop()
        }
      } catch (e) { /* ignore parse errors */ }
    }
  } catch (e) {
    wsConnected.value = false
  }
}

async function pollStats() {
  try {
    const { data } = await getRealtimeStats()
    stats.value = data
  } catch (e) { /* ignore */ }
}

export function useFiberStats() {
  onMounted(() => {
    pollStats()
    connectWs()
    timer = setInterval(pollStats, 10000)
  })
  onUnmounted(() => {
    if (timer) clearInterval(timer)
    if (ws) ws.close()
  })
  return { stats, recentChanges, wsConnected }
}
