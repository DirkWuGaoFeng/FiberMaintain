/**
 * 告警状态管理 — 当前告警查询 / WebSocket 告警事件累积
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getCurrentAlarms } from '@/api/fiber'
import type { AlarmRecord, AlarmSummary } from '@/types/alarm'
import type { AlarmEvent } from '@/types/events'

const MAX_RECENT_ALARMS = 50
const ALARM_POLL_INTERVAL = 30000

export const useAlarmStore = defineStore('alarm', () => {
  // ===== State =====
  /** 后端查询到的活跃告警 */
  const alarms = ref<AlarmRecord[]>([])
  /** WebSocket 推送的最近告警事件流 */
  const recentAlarms = ref<AlarmEvent[]>([])
  const loading = ref(false)
  const lastFetchTime = ref<number | null>(null)

  let pollTimer: ReturnType<typeof setInterval> | null = null

  // ===== Getters =====
  const summary = computed<AlarmSummary>(() => {
    // 合并 REST 查询结果与 WS 事件流进行统计
    let critical = 0
    let minor = 0
    let unspecified = 0

    for (const a of alarms.value) {
      if (a.alarm_level === 'CRITICAL') critical++
      else if (a.alarm_level === 'MINOR') minor++
      else unspecified++
    }
    for (const a of recentAlarms.value) {
      if (a.alarm_level === 'CRITICAL' || a.alarm_level === 'MAJOR') critical++
      else if (a.alarm_level === 'MINOR') minor++
      else unspecified++
    }

    return { total: critical + minor + unspecified, critical, minor, unspecified }
  })

  const criticalCount = computed(() => summary.value.critical)
  const minorCount = computed(() => summary.value.minor)

  /** 合并后的告警列表（WS 事件优先展示，最新在前） */
  const mergedAlarms = computed(() => {
    const wsItems: AlarmRecord[] = recentAlarms.value.map((e) => ({
      board_id: e.fiber_id,
      port_id: 0,
      alarm_level: e.alarm_level,
      raised_at: e.timestamp,
    }))
    return [...wsItems, ...alarms.value].slice(0, 20)
  })

  // ===== Actions =====

  /** 从后端查询当前活跃告警 */
  async function fetchCurrentAlarms(boardId?: number, portId?: number) {
    loading.value = true
    try {
      const { alarms: list } = await getCurrentAlarms(boardId, portId)
      alarms.value = list
      lastFetchTime.value = Date.now()
    } catch {
      // 后端不可用时保持现有数据
    } finally {
      loading.value = false
    }
  }

  /** 处理 WebSocket 告警事件 */
  function handleAlarmEvent(event: AlarmEvent) {
    recentAlarms.value.unshift(event)
    if (recentAlarms.value.length > MAX_RECENT_ALARMS) {
      recentAlarms.value = recentAlarms.value.slice(0, MAX_RECENT_ALARMS)
    }
  }

  /** 清空 WS 事件缓存 */
  function clearRecentAlarms() {
    recentAlarms.value = []
  }

  /** 启动告警轮询（30s 间隔） */
  function startPolling() {
    if (pollTimer) return
    fetchCurrentAlarms()
    pollTimer = setInterval(() => fetchCurrentAlarms(), ALARM_POLL_INTERVAL)
  }

  /** 停止告警轮询 */
  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  return {
    alarms,
    recentAlarms,
    loading,
    lastFetchTime,
    summary,
    criticalCount,
    minorCount,
    mergedAlarms,
    fetchCurrentAlarms,
    handleAlarmEvent,
    clearRecentAlarms,
    startPolling,
    stopPolling,
  }
})
