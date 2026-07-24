/**
 * 双模式数据同步：WS 订阅（实时）+ REST 轮询（10s 差异同步）。
 * WS 断线重连 + last_event_id 补拉。
 */
import { ref, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

const REST_URL = import.meta.env.VITE_FIBER_REST_URL || ''
const WS_URL = import.meta.env.VITE_FIBER_WS_URL || ''
const POLL_INTERVAL = 10_000
const HEARTBEAT_INTERVAL = 15_000
const BACKOFF = [3000, 6000, 12000, 30000]

export interface FiberStats {
  red_count: number
  yellow_count: number
  total_colored: number
  total_fibers: number
  active_alarms: number
}

export interface ColorEvent {
  fiber_id: number
  old_color: string
  new_color: string
  timestamp: string
}

export function useFiberStats() {
  const stats = ref<FiberStats>({
    red_count: 0, yellow_count: 0, total_colored: 0,
    total_fibers: 0, active_alarms: 0,
  })
  const recentChanges = ref<ColorEvent[]>([])
  const wsConnected = ref(false)
  const lastEventId = ref('')

  let ws: WebSocket | null = null
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  let reconnectAttempt = 0
  let disposed = false

  // ─── WebSocket ───
  function connectWS() {
    if (disposed) return
    const url = `${WS_URL}/ws/v1/events${lastEventId.value ? `?last_event_id=${lastEventId.value}` : ''}`
    ws = new WebSocket(url)

    ws.onopen = () => {
      wsConnected.value = true
      reconnectAttempt = 0
      // 订阅频道
      ws!.send(JSON.stringify({ action: 'subscribe', channels: ['fiber_stats', 'fiber_color', 'alarm'] }))
      // 心跳
      heartbeatTimer = setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ action: 'ping' }))
        }
      }, HEARTBEAT_INTERVAL)
    }

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data)
        if (msg.type === 'pong') return
        if (msg.event_id) lastEventId.value = msg.event_id

        if (msg.channel === 'fiber_stats' && msg.data) {
          // 增量更新
          Object.assign(stats.value, msg.data)
        } else if (msg.channel === 'fiber_color' && msg.data) {
          recentChanges.value.unshift(msg.data as ColorEvent)
          if (recentChanges.value.length > 50) recentChanges.value.pop()
        }
      } catch { /* ignore parse errors */ }
    }

    ws.onclose = () => {
      wsConnected.value = false
      clearInterval(heartbeatTimer!)
      scheduleReconnect()
    }

    ws.onerror = () => { ws?.close() }
  }

  function scheduleReconnect() {
    if (disposed) return
    const delay = BACKOFF[Math.min(reconnectAttempt, BACKOFF.length - 1)]
    reconnectAttempt++
    setTimeout(connectWS, delay)
  }

  // ─── REST 轮询（差异同步） ───
  async function pollStats() {
    try {
      const { data } = await axios.get(`${REST_URL}/api/v1/fibers/stats/realtime`)
      const d = data.data || data
      // 增量对比
      if (JSON.stringify(d) !== JSON.stringify(stats.value)) {
        Object.assign(stats.value, d)
      }
    } catch { /* 后端不可用时静默 */ }
  }

  onMounted(() => {
    connectWS()
    pollStats()
    pollTimer = setInterval(pollStats, POLL_INTERVAL)
  })

  onUnmounted(() => {
    disposed = true
    ws?.close()
    clearInterval(pollTimer!)
    clearInterval(heartbeatTimer!)
  })

  return { stats, recentChanges, wsConnected }
}