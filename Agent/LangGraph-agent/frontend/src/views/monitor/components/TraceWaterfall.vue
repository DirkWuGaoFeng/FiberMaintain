<template>
  <div class="trace-waterfall">
    <!-- 跟踪列表 -->
    <div class="trace-list-panel">
      <div class="panel-header">
        <span class="panel-title">{{ $t('monitor.traceList') }}</span>
        <el-button size="small" text @click="loadTraces">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
      <div class="trace-items" v-loading="loadingTraces">
        <div v-if="!traces.length" class="no-data">{{ $t('common.noData') }}</div>
        <div
          v-for="trace in traces"
          :key="trace.trace_id"
          class="trace-item"
          :class="{ active: selectedTraceId === trace.trace_id }"
          @click="selectTrace(trace)"
        >
          <div class="trace-item-top">
            <span class="trace-input" :title="trace.user_input">{{ trace.user_input }}</span>
            <el-tag :type="statusType(trace.status)" size="small" effect="plain">
              {{ trace.status }}
            </el-tag>
          </div>
          <div class="trace-item-bottom">
            <span class="trace-path">{{ trace.processing_path }}</span>
            <span class="trace-duration" :class="{ slow: trace.total_ms > 5000 }">
              {{ trace.total_ms }}ms
            </span>
            <span class="trace-time">{{ formatTime(trace.timestamp) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 瀑布图详情 -->
    <div class="waterfall-panel">
      <div class="panel-header">
        <span class="panel-title">{{ $t('monitor.traceWaterfall') }}</span>
        <span v-if="traceDetail" class="trace-meta">
          {{ traceDetail.span_count }} spans · {{ traceDetail.total_ms }}ms
        </span>
      </div>
      <div v-if="!traceDetail" class="no-data waterfall-placeholder">
        {{ $t('monitor.selectTraceHint') }}
      </div>
      <div v-else ref="waterfallChartRef" class="waterfall-chart" />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Trace 瀑布图 — 展示各节点执行耗时 [v7.2]
 *
 * 左侧：最近跟踪列表（可点击选择）
 * 右侧：ECharts 横向条形图（瀑布图）展示各 Span 耗时
 */
import { ref, onMounted } from 'vue'
import { useECharts } from '@/composables/useECharts'
import { fetchRecentTraces, fetchTraceDetail } from '@/api/trace'
import type { TraceSummary, TraceDetail } from '@/api/trace'
import type { EChartsOption } from 'echarts'

const traces = ref<TraceSummary[]>([])
const traceDetail = ref<TraceDetail | null>(null)
const selectedTraceId = ref('')
const loadingTraces = ref(false)

const waterfallChartRef = ref<HTMLElement | null>(null)
const { setOption } = useECharts(waterfallChartRef)

/** 加载最近跟踪列表 */
async function loadTraces() {
  loadingTraces.value = true
  try {
    traces.value = await fetchRecentTraces(20)
  } catch {
    traces.value = []
  } finally {
    loadingTraces.value = false
  }
}

/** 选择一条跟踪，加载详情并渲染瀑布图 */
async function selectTrace(trace: TraceSummary) {
  selectedTraceId.value = trace.trace_id
  const detail = await fetchTraceDetail(trace.trace_id)
  if (!detail) return
  traceDetail.value = detail
  renderWaterfall(detail)
}

/** 渲染瀑布图 */
function renderWaterfall(detail: TraceDetail) {
  const spans = detail.phase_breakdown?.length
    ? detail.phase_breakdown.map((p) => ({
        node: p.node,
        duration_ms: p.duration_ms,
        is_slow: p.is_slow,
      }))
    : detail.spans.map((s) => ({
        node: s.node_name,
        duration_ms: s.duration_ms ?? 0,
        is_slow: s.is_slow,
      }))

  if (!spans.length) return

  const nodes = spans.map((s) => s.node)
  const durations = spans.map((s) => s.duration_ms)
  const colors = spans.map((s) => (s.is_slow ? '#f56c6c' : '#409eff'))

  const option: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        const idx = p.dataIndex
        const span = spans[idx]
        const pct = detail.total_ms > 0 ? ((span.duration_ms / detail.total_ms) * 100).toFixed(1) : '0'
        return `<b>${span.node}</b><br/>${span.duration_ms}ms (${pct}%)${span.is_slow ? '<br/><span style="color:#f56c6c">⚠ SLOW</span>' : ''}`
      },
    },
    grid: { top: 12, bottom: 24, left: 130, right: 50 },
    xAxis: {
      type: 'value',
      name: 'ms',
      axisLabel: { fontSize: 9 },
      splitLine: { lineStyle: { type: 'dashed', opacity: 0.4 } },
    },
    yAxis: {
      type: 'category',
      data: nodes,
      inverse: true,
      axisLabel: { fontSize: 10, width: 120, overflow: 'truncate' },
      axisTick: { show: false },
    },
    series: [
      {
        type: 'bar',
        data: durations.map((d, i) => ({
          value: d,
          itemStyle: {
            color: colors[i],
            borderRadius: [0, 3, 3, 0],
          },
        })),
        barMaxWidth: 16,
        label: {
          show: true,
          position: 'right',
          fontSize: 9,
          formatter: (p: any) => `${p.value}ms`,
        },
      },
    ],
    animationDuration: 400,
  }

  // 等待 DOM 更新后渲染
  requestAnimationFrame(() => setOption(option, true))
}

function statusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'SUCCESS') return 'success'
  if (status === 'SLOW') return 'warning'
  if (status === 'ERROR' || status === 'TIMEOUT') return 'danger'
  return 'info'
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    return ts
  }
}

onMounted(() => {
  loadTraces()
})
</script>

<style scoped lang="scss">
.trace-waterfall {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 12px;
  height: 100%;
  min-height: 0;

  @media (max-width: 900px) {
    grid-template-columns: 1fr;
    grid-template-rows: 180px 1fr;
  }
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;

  .panel-title {
    font-size: 12px;
    font-weight: 700;
    color: var(--fa-text-secondary);
  }

  .trace-meta {
    font-size: 10px;
    color: var(--fa-text-muted);
    font-family: 'JetBrains Mono', monospace;
  }
}

.trace-list-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;

  .trace-items {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
}

.trace-item {
  padding: 8px 10px;
  border: 1px solid var(--fa-border-color);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    border-color: var(--el-color-primary-light-5);
    background: var(--el-color-primary-light-9);
  }

  &.active {
    border-color: var(--el-color-primary);
    background: var(--el-color-primary-light-9);
  }

  .trace-item-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;

    .trace-input {
      font-size: 11px;
      font-weight: 500;
      color: var(--fa-text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
    }
  }

  .trace-item-bottom {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
    font-size: 10px;
    color: var(--fa-text-muted);

    .trace-path {
      font-family: 'JetBrains Mono', monospace;
      background: var(--fa-bg-primary);
      padding: 1px 4px;
      border-radius: 3px;
    }

    .trace-duration {
      font-family: 'JetBrains Mono', monospace;
      font-weight: 600;

      &.slow {
        color: var(--fa-danger);
      }
    }

    .trace-time {
      margin-left: auto;
    }
  }
}

.waterfall-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;

  .waterfall-chart {
    flex: 1;
    min-height: 200px;
  }

  .waterfall-placeholder {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
  }
}

.no-data {
  text-align: center;
  font-size: 12px;
  color: var(--fa-text-muted);
  padding: 20px 0;
}
</style>
