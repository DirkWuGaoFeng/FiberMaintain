/**
 * 应用全局状态 — 主题 / WebSocket 连接 / 布局
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { WebSocketManager } from '@/api/websocket'
import type { WsConnectionState, WsEvent, AlarmEvent, FiberColorEvent, FiberStatsEvent } from '@/types/events'
import { ElNotification } from 'element-plus'
import { useTopologyStore } from '@/stores/topology'
import { useAlarmStore } from '@/stores/alarm'

const THEME_KEY = 'fiber-agent-theme'

export const useAppStore = defineStore('app', () => {
  // ===== 主题 =====
  const isDark = ref(false)

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY)
    if (saved === 'dark') {
      isDark.value = true
    } else if (saved === 'light') {
      isDark.value = false
    } else {
      // 跟随系统
      isDark.value = window.matchMedia('(prefers-color-scheme: dark)').matches
    }
    applyTheme()
  }

  function toggleTheme() {
    isDark.value = !isDark.value
    localStorage.setItem(THEME_KEY, isDark.value ? 'dark' : 'light')
    applyTheme()
  }

  function applyTheme() {
    document.documentElement.classList.toggle('dark', isDark.value)
  }

  // ===== WebSocket =====
  const wsState = ref<WsConnectionState>('disconnected')
  const wsConnected = computed(() => wsState.value === 'connected')
  const lastAlarm = ref<AlarmEvent | null>(null)
  const fiberStats = ref<FiberStatsEvent['data'] | null>(null)
  const alarmCount = ref(0)

  let wsManager: WebSocketManager | null = null

  function connectWebSocket() {
    if (wsManager) return

    // 开发环境通过 Vite proxy: /ws/v1/events → ws://localhost:8081
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/v1/events`

    wsManager = new WebSocketManager(wsUrl, {
      heartbeatInterval: 15000,
      reconnectBackoff: [3, 6, 12, 30],
      onStateChange: (state) => {
        wsState.value = state
      },
      onEvent: handleWsEvent,
    })

    wsManager.connect()
  }

  function disconnectWebSocket() {
    wsManager?.disconnect()
    wsManager = null
    wsState.value = 'disconnected'
  }

  function reconnectWebSocket() {
    wsManager?.reconnect()
  }

  function handleWsEvent(event: WsEvent) {
    const topologyStore = useTopologyStore()
    const alarmStore = useAlarmStore()

    switch (event.type) {
      case 'alarm': {
        lastAlarm.value = event
        alarmCount.value++
        // 分发到告警 store
        alarmStore.handleAlarmEvent(event)
        // 严重告警弹通知
        if (event.alarm_level === 'CRITICAL' || event.alarm_level === 'MAJOR') {
          ElNotification({
            title: '告警通知',
            message: `光纤 ${event.fiber_id} 触发 ${event.alarm_level} 告警`,
            type: 'error',
            duration: 8000,
          })
        }
        break
      }
      case 'fiber_color': {
        const colorEvent = event as FiberColorEvent
        // 分发到拓扑 store 更新本地缓存
        topologyStore.handleColorEvent(colorEvent)
        if (colorEvent.new_color === 'RED') {
          ElNotification({
            title: '色标变更',
            message: `光纤 ${colorEvent.fiber_id} 色标升级为 RED`,
            type: 'warning',
            duration: 6000,
          })
        }
        break
      }
      case 'fiber_stats': {
        fiberStats.value = (event as FiberStatsEvent).data
        // 分发到拓扑 store 更新统计
        topologyStore.handleStatsEvent(event as FiberStatsEvent)
        break
      }
      default:
        break
    }
  }

  return {
    // 主题
    isDark,
    initTheme,
    toggleTheme,
    // WebSocket
    wsState,
    wsConnected,
    lastAlarm,
    fiberStats,
    alarmCount,
    connectWebSocket,
    disconnectWebSocket,
    reconnectWebSocket,
  }
})
