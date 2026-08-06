<template>
  <div class="fiber-trend-chart">
    <div class="panel-header">
      <span class="panel-title">{{ $t('fiberColor.trendTitle') }}</span>
      <el-radio-group v-model="range" size="small" @change="handleRangeChange">
        <el-radio-button value="hour">{{ $t('fiberColor.hour') }}</el-radio-button>
        <el-radio-button value="day">{{ $t('fiberColor.day') }}</el-radio-button>
        <el-radio-button value="week">{{ $t('fiberColor.week') }}</el-radio-button>
      </el-radio-group>
    </div>

    <div class="chart-wrapper">
      <div v-if="topologyStore.trendPoints.length === 0" class="no-data-overlay">
        {{ $t('common.noData') }}
      </div>
      <div ref="chartRef" class="chart-body" />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 连纤变色趋势图 — 按时间段显示红/黄连纤数量变化
 * 支持小时/天/周视图切换，异常时段 markPoint 标注
 */
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTopologyStore } from '@/stores/topology'
import { useECharts } from '@/composables/useECharts'
import type { TrendRange } from '@/types/topology'
import type { EChartsOption } from 'echarts'

const { t } = useI18n()
const topologyStore = useTopologyStore()

const range = ref<TrendRange>(topologyStore.trendRange)
const chartRef = ref<HTMLElement | null>(null)

function handleRangeChange(val: string | number | boolean | undefined) {
  if (val) topologyStore.fetchTrend(val as TrendRange)
}

/** 检测异常突增点（red_count 相比前一个点增长 >= 2） */
function findAnomalyPoints(): { name: string; xAxis: string; yAxis: number }[] {
  const points = topologyStore.trendPoints
  const anomalies: { name: string; xAxis: string; yAxis: number }[] = []
  for (let i = 1; i < points.length; i++) {
    const diff = points[i].red_count - points[i - 1].red_count
    if (diff >= 2) {
      anomalies.push({ name: `+${diff}`, xAxis: formatTs(points[i].timestamp), yAxis: points[i].red_count })
    }
  }
  return anomalies.slice(0, 10) // 最多标注 10 个
}

function formatTs(ts: string): string {
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts
  if (range.value === 'hour') {
    return d.toLocaleTimeString('zh-CN', { hour12: false, minute: '2-digit', second: '2-digit' })
  }
  if (range.value === 'day') {
    return d.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' })
  }
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const chartOptions = computed<EChartsOption>(() => {
  const points = topologyStore.trendPoints
  const times = points.map((p) => formatTs(p.timestamp))
  const reds = points.map((p) => p.red_count)
  const yellows = points.map((p) => p.yellow_count)
  const totals = points.map((p) => p.total_colored)
  const anomalies = findAnomalyPoints()

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', crossStyle: { color: '#999' } },
    },
    legend: {
      data: [t('fiberColor.redLine'), t('fiberColor.yellowLine'), t('fiberColor.totalColored')],
      top: 0,
      right: 0,
      textStyle: { fontSize: 10 },
    },
    grid: { top: 30, bottom: 26, left: 36, right: 14 },
    xAxis: {
      type: 'category',
      data: times,
      boundaryGap: false,
      axisLabel: { fontSize: 9, rotate: times.length > 20 ? 30 : 0 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { fontSize: 9 },
      splitLine: { lineStyle: { type: 'dashed', opacity: 0.5 } },
    },
    series: [
      {
        name: t('fiberColor.redLine'),
        type: 'line',
        data: reds,
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { color: '#f56c6c', width: 2 },
        itemStyle: { color: '#f56c6c' },
        areaStyle: { color: 'rgba(245, 108, 108, 0.1)' },
        markPoint: anomalies.length > 0
          ? {
              data: anomalies,
              symbol: 'pin',
              symbolSize: 32,
              itemStyle: { color: '#f56c6c' },
              label: { fontSize: 9, color: '#fff' },
            }
          : undefined,
      },
      {
        name: t('fiberColor.yellowLine'),
        type: 'line',
        data: yellows,
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { color: '#e6a23c', width: 2 },
        itemStyle: { color: '#e6a23c' },
        areaStyle: { color: 'rgba(230, 162, 60, 0.08)' },
      },
      {
        name: t('fiberColor.totalColored'),
        type: 'line',
        data: totals,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#909399', width: 1.5, type: 'dashed' },
        itemStyle: { color: '#909399' },
      },
    ],
    animationDuration: 500,
  }
})

useECharts(chartRef, chartOptions)

// 同步外部 range 变化
watch(() => topologyStore.trendRange, (val) => {
  range.value = val
})
</script>

<style scoped lang="scss">
.fiber-trend-chart {
  border: 1px solid var(--fa-border-color);
  border-radius: 10px;
  background: var(--fa-bg-secondary);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;

  .panel-title {
    font-size: 13px;
    font-weight: 700;
    color: var(--fa-text-primary);
    letter-spacing: 0.3px;
  }
}

.chart-wrapper {
  position: relative;
  flex: 1;
  min-height: 0;

  .no-data-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    color: var(--fa-text-muted);
    z-index: 1;
    pointer-events: none;
  }

  .chart-body {
    width: 100%;
    height: 100%;
    min-height: 200px;
  }
}
</style>
