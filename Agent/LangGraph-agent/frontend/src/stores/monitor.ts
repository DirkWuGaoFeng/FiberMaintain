/**
 * 监控状态管理 — 指标轮询 / 降级状态 / 健康状态
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getHealth, getMetricsSummary, getDegradationStatus } from '@/api/system'
import type { MetricsSummary, MetricsSnapshot, DegradationStatus, HealthResponse } from '@/types/metrics'

const POLL_INTERVAL = 15000
const MAX_SNAPSHOTS = 120 // 保留 30 分钟趋势数据

export const useMonitorStore = defineStore('monitor', () => {
  const metrics = ref<MetricsSummary | null>(null)
  const snapshots = ref<MetricsSnapshot[]>([])
  const degradation = ref<DegradationStatus | null>(null)
  const health = ref<HealthResponse | null>(null)
  const degradationLevel = ref(0)
  const lastUpdated = ref<number | null>(null)
  const pollingActive = ref(false)

  let pollTimer: ReturnType<typeof setInterval> | null = null

  /** 拉取一次全部监控数据 */
  async function fetchAll() {
    const results = await Promise.allSettled([getMetricsSummary(), getDegradationStatus(), getHealth()])

    if (results[0].status === 'fulfilled') {
      metrics.value = results[0].value
      degradationLevel.value = results[0].value.degradationLevel
      snapshots.value.push({ timestamp: Date.now(), summary: results[0].value })
      if (snapshots.value.length > MAX_SNAPSHOTS) {
        snapshots.value = snapshots.value.slice(-MAX_SNAPSHOTS)
      }
    }

    if (results[1].status === 'fulfilled') {
      degradation.value = results[1].value
      degradationLevel.value = results[1].value.level
    }

    if (results[2].status === 'fulfilled') {
      health.value = results[2].value
    }

    lastUpdated.value = Date.now()
  }

  /** 启动轮询 */
  function startPolling() {
    if (pollingActive.value) return
    pollingActive.value = true
    fetchAll()
    pollTimer = setInterval(fetchAll, POLL_INTERVAL)
  }

  /** 停止轮询 */
  function stopPolling() {
    pollingActive.value = false
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  return {
    metrics,
    snapshots,
    degradation,
    health,
    degradationLevel,
    lastUpdated,
    pollingActive,
    fetchAll,
    startPolling,
    stopPolling,
  }
})
