<template>
  <div class="monitor-view">
    <!-- 页头 -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">{{ $t('monitor.title') }}</h2>
        <el-tag :type="degradationTagType" size="small" effect="dark">
          {{ $t(`monitor.levels.${monitorStore.degradationLevel}`) }}
        </el-tag>
      </div>
      <div class="header-right">
        <span class="last-updated" v-if="monitorStore.lastUpdated">
          {{ $t('monitor.lastUpdated') }}: {{ formatTime(monitorStore.lastUpdated) }}
        </span>
        <el-switch
          v-model="autoRefresh"
          :active-text="$t('monitor.autoRefresh')"
          size="small"
          @change="togglePolling"
        />
        <el-button size="small" @click="monitorStore.fetchAll()">
          <el-icon><Refresh /></el-icon>
        </el-button>
        <el-button size="small" type="warning" plain :loading="reloading" @click="handleRuleReload">
          {{ $t('monitor.ruleReload') }}
        </el-button>
      </div>
    </div>

    <!-- 总览卡片 -->
    <div class="overview-row">
      <div class="overview-card requests">
        <div class="card-icon">📡</div>
        <div class="card-body">
          <span class="card-value">{{ totalRequests }}</span>
          <span class="card-label">{{ $t('monitor.totalRequests') }}</span>
        </div>
      </div>
      <div class="overview-card rule-hit">
        <div class="card-icon">🎯</div>
        <div class="card-body">
          <span class="card-value">{{ ruleHitRate }}%</span>
          <span class="card-label">{{ $t('monitor.ruleHitRate') }}</span>
        </div>
      </div>
      <div class="overview-card latency">
        <div class="card-icon">⏱</div>
        <div class="card-body">
          <span class="card-value">{{ avgLatency }}<small>ms</small></span>
          <span class="card-label">{{ $t('monitor.avgLatency') }}</span>
        </div>
      </div>
      <div class="overview-card degradation">
        <div class="card-icon">{{ monitorStore.degradationLevel === 0 ? '✅' : '⚠️' }}</div>
        <div class="card-body">
          <span class="card-value">L{{ monitorStore.degradationLevel }}</span>
          <span class="card-label">{{ $t('monitor.degradationLevel') }}</span>
        </div>
      </div>
    </div>

    <!-- 后端状态监控区域 -->
    <div class="backend-section">
      <div class="section-title-row">
        <span class="section-title">{{ $t('fiberColor.title') }}</span>
        <span class="section-hint">C++ Backend · :8080</span>
      </div>
      <AlarmPanel />
      <div class="fiber-grid">
        <FiberColorStats />
        <FiberTrendChart />
      </div>
    </div>

    <!-- 图表区域 -->
    <div class="charts-grid">
      <!-- 请求趋势 -->
      <div class="chart-card trend">
        <div class="chart-title">{{ $t('monitor.requestTrend') }}</div>
        <div ref="trendChartRef" class="chart-body" />
      </div>

      <!-- 工具调用统计 -->
      <div class="chart-card tools">
        <div class="chart-title">{{ $t('monitor.toolCallStats') }}</div>
        <div ref="toolChartRef" class="chart-body" />
      </div>

      <!-- Token 消耗 -->
      <div class="chart-card tokens">
        <div class="chart-title">{{ $t('monitor.tokenUsage') }}</div>
        <div ref="tokenChartRef" class="chart-body" />
      </div>

      <!-- 健康矩阵 -->
      <div class="chart-card health">
        <div class="chart-title">{{ $t('monitor.healthMatrix') }}</div>
        <div class="health-list">
          <div v-if="!monitorStore.health?.components?.length" class="no-health">
            {{ $t('common.noData') }}
          </div>
          <div
            v-for="comp in monitorStore.health?.components || []"
            :key="comp.name"
            class="health-item"
          >
            <span class="health-dot" :class="comp.status" />
            <span class="health-name">{{ comp.name }}</span>
            <el-tag :type="healthType(comp.status)" size="small" effect="plain">
              {{ $t(`monitor.${comp.status === 'healthy' ? 'healthy' : comp.status === 'degraded' ? 'degraded' : 'unhealthy'}`) }}
            </el-tag>
            <span v-if="comp.latencyMs" class="health-latency">{{ comp.latencyMs }}ms</span>
          </div>

          <!-- LLM 梯度状态 -->
          <div class="llm-section">
            <div class="section-label">LLM Tiers</div>
            <div class="health-item" v-for="(ok, tier) in llmStatus" :key="tier">
              <span class="health-dot" :class="ok ? 'healthy' : 'unhealthy'" />
              <span class="health-name">{{ $t(`monitor.llmTiers.${tier}`) }}</span>
              <el-tag :type="ok ? 'success' : 'danger'" size="small" effect="plain">
                {{ ok ? 'Online' : 'Offline' }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Trace 瀑布图区域 -->
    <div class="trace-section">
      <div class="section-title-row">
        <span class="section-title">{{ $t('monitor.traceWaterfall') }}</span>
        <span class="section-hint">RequestTracer v7.2</span>
      </div>
      <div class="trace-container">
        <TraceWaterfall />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 运行监控面板 — Prometheus 指标可视化 + 降级状态 + 健康矩阵
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useMonitorStore } from '@/stores/monitor'
import { useTopologyStore } from '@/stores/topology'
import { useAlarmStore } from '@/stores/alarm'
import { reloadRules } from '@/api/system'
import { useECharts } from '@/composables/useECharts'
import type { EChartsOption } from 'echarts'
import AlarmPanel from './components/AlarmPanel.vue'
import FiberColorStats from './components/FiberColorStats.vue'
import FiberTrendChart from './components/FiberTrendChart.vue'
import TraceWaterfall from './components/TraceWaterfall.vue'

const { t } = useI18n()
const monitorStore = useMonitorStore()
const topologyStore = useTopologyStore()
const alarmStore = useAlarmStore()

const autoRefresh = ref(true)
const reloading = ref(false)

// ===== 图表 =====
const trendChartRef = ref<HTMLElement | null>(null)
const toolChartRef = ref<HTMLElement | null>(null)
const tokenChartRef = ref<HTMLElement | null>(null)

const trendOptions = computed<EChartsOption>(() => buildTrendOptions())
const toolOptions = computed<EChartsOption>(() => buildToolOptions())
const tokenOptions = computed<EChartsOption>(() => buildTokenOptions())

useECharts(trendChartRef, trendOptions)
useECharts(toolChartRef, toolOptions)
useECharts(tokenChartRef, tokenOptions)

// ===== 计算指标 =====
const totalRequests = computed(() => {
  const dist = monitorStore.metrics?.requestTotal || {}
  return Object.values(dist).reduce((a, b) => a + b, 0)
})

const ruleHitRate = computed(() => {
  const total = totalRequests.value
  if (total === 0) return 0
  const hits = Object.values(monitorStore.metrics?.ruleHitTotal || {}).reduce((a, b) => a + b, 0)
  return Math.min(100, Math.round((hits / total) * 100))
})

const avgLatency = computed(() => monitorStore.metrics?.requestDuration.avg ?? 0)

const llmStatus = computed(() => {
  const d = monitorStore.degradation
  return d?.llm_status || { primary: false, secondary: false, tertiary: false }
})

const degradationTagType = computed(() => {
  const level = monitorStore.degradationLevel
  if (level === 0) return 'success'
  if (level <= 2) return 'warning'
  return 'danger'
})

// ===== 图表构建 =====
function buildTrendOptions(): EChartsOption {
  const snaps = monitorStore.snapshots.slice(-40)
  const times = snaps.map((s) =>
    new Date(s.timestamp).toLocaleTimeString('zh-CN', { hour12: false, minute: '2-digit', second: '2-digit' }),
  )
  const totals = snaps.map((s) =>
    Object.values(s.summary.requestTotal || {}).reduce((a, b) => a + b, 0),
  )
  const latencies = snaps.map((s) => s.summary.requestDuration.avg)

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Requests', 'Latency(ms)'], top: 0, right: 0, textStyle: { fontSize: 10 } },
    grid: { top: 28, bottom: 24, left: 40, right: 40 },
    xAxis: { type: 'category', data: times, axisLabel: { fontSize: 9 } },
    yAxis: [
      { type: 'value', name: 'req', axisLabel: { fontSize: 9 } },
      { type: 'value', name: 'ms', axisLabel: { fontSize: 9 } },
    ],
    series: [
      {
        name: 'Requests',
        type: 'bar',
        data: totals,
        itemStyle: { color: 'rgba(64, 158, 255, 0.7)', borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 12,
      },
      {
        name: 'Latency(ms)',
        type: 'line',
        yAxisIndex: 1,
        data: latencies,
        smooth: true,
        lineStyle: { color: '#e6a23c', width: 2 },
        itemStyle: { color: '#e6a23c' },
        areaStyle: { color: 'rgba(230, 162, 60, 0.08)' },
      },
    ],
  }
}

function buildToolOptions(): EChartsOption {
  const toolCalls = monitorStore.metrics?.toolCalls || {}
  const names = Object.keys(toolCalls).slice(0, 12)
  const success = names.map((n) => toolCalls[n]?.success || 0)
  const error = names.map((n) => toolCalls[n]?.error || 0)

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: [t('monitor.successCalls'), t('monitor.failedCalls')], top: 0, right: 0, textStyle: { fontSize: 10 } },
    grid: { top: 28, bottom: 50, left: 40, right: 12 },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: { fontSize: 9, rotate: 35, interval: 0 },
    },
    yAxis: { type: 'value', axisLabel: { fontSize: 9 } },
    series: [
      {
        name: t('monitor.successCalls'),
        type: 'bar',
        stack: 'total',
        data: success,
        itemStyle: { color: '#67c23a', borderRadius: [0, 0, 0, 0] },
        barMaxWidth: 18,
      },
      {
        name: t('monitor.failedCalls'),
        type: 'bar',
        stack: 'total',
        data: error,
        itemStyle: { color: '#f56c6c', borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 18,
      },
    ],
  }
}

function buildTokenOptions(): EChartsOption {
  const usage = monitorStore.metrics?.tokenUsage || {}
  const data = Object.entries(usage).map(([name, value]) => ({ name, value }))

  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [
      {
        type: 'pie',
        radius: ['40%', '68%'],
        center: ['50%', '55%'],
        data: data.length > 0 ? data : [{ name: 'N/A', value: 0 }],
        label: { fontSize: 10 },
        itemStyle: { borderRadius: 4, borderColor: 'var(--fa-bg-secondary)', borderWidth: 2 },
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.2)' },
        },
      },
    ],
  }
}

// ===== 操作 =====
function healthType(status: string): 'success' | 'warning' | 'danger' {
  if (status === 'healthy') return 'success'
  if (status === 'degraded') return 'warning'
  return 'danger'
}

function togglePolling(val: boolean | string | number) {
  if (val) monitorStore.startPolling()
  else monitorStore.stopPolling()
}

async function handleRuleReload() {
  reloading.value = true
  try {
    const result = await reloadRules()
    ElMessage.success(t('monitor.ruleReloadSuccess', { count: result.rules_loaded }))
  } catch (e) {
    ElMessage.error(`${t('common.failed')}: ${e}`)
  } finally {
    reloading.value = false
  }
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false })
}

onMounted(() => {
  monitorStore.startPolling()
  // 后端状态监控：拉取连纤统计 + 告警数据
  topologyStore.fetchAll()
  topologyStore.startPolling()
  alarmStore.startPolling()
})

onUnmounted(() => {
  monitorStore.stopPolling()
  topologyStore.stopPolling()
  alarmStore.stopPolling()
})
</script>

<style scoped lang="scss">
.monitor-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
  padding: 16px 20px;
  gap: 14px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;

  .header-left {
    display: flex;
    align-items: center;
    gap: 12px;

    .page-title {
      margin: 0;
      font-size: 16px;
      font-weight: 700;
      color: var(--fa-text-primary);
    }
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 12px;

    .last-updated {
      font-size: 11px;
      color: var(--fa-text-muted);
    }
  }
}

.overview-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;

  @media (max-width: 900px) {
    grid-template-columns: repeat(2, 1fr);
  }

  .overview-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px;
    border: 1px solid var(--fa-border-color);
    border-radius: 10px;
    background: var(--fa-bg-secondary);
    transition: transform 0.15s, box-shadow 0.15s;

    &:hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 16px rgba(0, 0, 0, 0.07);
    }

    .card-icon {
      font-size: 24px;
    }

    .card-body {
      display: flex;
      flex-direction: column;

      .card-value {
        font-size: 22px;
        font-weight: 800;
        color: var(--fa-text-primary);
        font-family: 'JetBrains Mono', monospace;

        small {
          font-size: 12px;
          font-weight: 500;
          color: var(--fa-text-muted);
        }
      }

      .card-label {
        font-size: 11px;
        color: var(--fa-text-muted);
      }
    }

    &.requests { border-left: 3px solid #409eff; }
    &.rule-hit { border-left: 3px solid #67c23a; }
    &.latency { border-left: 3px solid #e6a23c; }
    &.degradation { border-left: 3px solid #9b59b6; }
  }
}

// ===== 后端状态监控区域 =====
.backend-section {
  display: flex;
  flex-direction: column;
  gap: 12px;

  .section-title-row {
    display: flex;
    align-items: baseline;
    gap: 10px;

    .section-title {
      font-size: 14px;
      font-weight: 700;
      color: var(--fa-text-primary);
    }

    .section-hint {
      font-size: 10px;
      color: var(--fa-text-muted);
      font-family: 'JetBrains Mono', monospace;
    }
  }

  .fiber-grid {
    display: grid;
    grid-template-columns: 1fr 2fr;
    gap: 12px;

    @media (max-width: 1000px) {
      grid-template-columns: 1fr;
    }
  }
}

.charts-grid {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  grid-template-rows: 260px 260px;
  gap: 12px;
  min-height: 520px;

  @media (max-width: 1000px) {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
  }

  .chart-card {
    border: 1px solid var(--fa-border-color);
    border-radius: 10px;
    background: var(--fa-bg-secondary);
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    min-height: 0;

    .chart-title {
      font-size: 12px;
      font-weight: 700;
      color: var(--fa-text-secondary);
      margin-bottom: 8px;
    }

    .chart-body {
      flex: 1;
      min-height: 0;
    }

    &.trend {
      grid-column: 1 / 2;
    }

    &.health {
      grid-row: 1 / 3;
      grid-column: 2 / 3;
    }
  }
}

.health-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;

  .no-health {
    text-align: center;
    font-size: 12px;
    color: var(--fa-text-muted);
    padding: 20px 0;
  }

  .health-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    border: 1px solid var(--fa-border-color);
    border-radius: 6px;

    .health-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;

      &.healthy { background: var(--fa-success); }
      &.degraded { background: var(--fa-warning); }
      &.unhealthy { background: var(--fa-danger); animation: pulse 1s infinite; }
    }

    .health-name {
      flex: 1;
      font-size: 12px;
      font-weight: 500;
      color: var(--fa-text-primary);
    }

    .health-latency {
      font-size: 10px;
      color: var(--fa-text-muted);
      font-family: monospace;
    }
  }

  .llm-section {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px dashed var(--fa-border-color);
    display: flex;
    flex-direction: column;
    gap: 8px;

    .section-label {
      font-size: 10px;
      font-weight: 700;
      color: var(--fa-text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
  }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

// ===== Trace 瀑布图区域 =====
.trace-section {
  display: flex;
  flex-direction: column;
  gap: 10px;

  .section-title-row {
    display: flex;
    align-items: baseline;
    gap: 10px;

    .section-title {
      font-size: 14px;
      font-weight: 700;
      color: var(--fa-text-primary);
    }

    .section-hint {
      font-size: 10px;
      color: var(--fa-text-muted);
      font-family: 'JetBrains Mono', monospace;
    }
  }

  .trace-container {
    border: 1px solid var(--fa-border-color);
    border-radius: 10px;
    background: var(--fa-bg-secondary);
    padding: 14px;
    height: 320px;
  }
}
</style>
