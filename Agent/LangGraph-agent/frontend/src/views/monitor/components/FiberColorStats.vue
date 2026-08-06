<template>
  <div class="fiber-color-stats">
    <div class="panel-header">
      <span class="panel-title">{{ $t('fiberColor.title') }}</span>
      <div class="ws-indicator" :class="{ online: appStore.wsConnected }">
        <span class="ws-dot" />
        <span class="ws-text">{{ appStore.wsConnected ? 'WS' : 'OFF' }}</span>
      </div>
    </div>

    <div class="stats-body">
      <!-- 三色统计 -->
      <div class="color-cards">
        <div class="color-card red">
          <div class="color-bar" />
          <div class="color-content">
            <Transition name="num" mode="out-in">
              <span class="color-value" :key="topologyStore.redCount">{{ topologyStore.redCount }}</span>
            </Transition>
            <span class="color-label">{{ $t('fiberColor.redCount') }}</span>
          </div>
        </div>
        <div class="color-card yellow">
          <div class="color-bar" />
          <div class="color-content">
            <Transition name="num" mode="out-in">
              <span class="color-value" :key="topologyStore.yellowCount">{{ topologyStore.yellowCount }}</span>
            </Transition>
            <span class="color-label">{{ $t('fiberColor.yellowCount') }}</span>
          </div>
        </div>
        <div class="color-card green">
          <div class="color-bar" />
          <div class="color-content">
            <Transition name="num" mode="out-in">
              <span class="color-value" :key="topologyStore.greenCount">{{ topologyStore.greenCount }}</span>
            </Transition>
            <span class="color-label">{{ $t('fiberColor.greenCount') }}</span>
          </div>
        </div>
      </div>

      <!-- 环形占比图 -->
      <div ref="pieChartRef" class="pie-chart" />

      <!-- 底部汇总 -->
      <div class="stats-footer">
        <div class="footer-item">
          <span class="footer-value">{{ topologyStore.stats?.total_fibers ?? '--' }}</span>
          <span class="footer-label">{{ $t('fiberColor.totalFibers') }}</span>
        </div>
        <div class="footer-divider" />
        <div class="footer-item">
          <span class="footer-value alarm-num">{{ topologyStore.stats?.active_alarms ?? '--' }}</span>
          <span class="footer-label">{{ $t('fiberColor.activeAlarms') }}</span>
        </div>
        <div class="footer-divider" />
        <div class="footer-item">
          <span class="footer-value">{{ lastUpdateLabel }}</span>
          <span class="footer-label">{{ $t('monitor.lastUpdated') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 连纤色标监控 — 三色统计卡片 + 环形占比图 + 实时状态
 */
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTopologyStore } from '@/stores/topology'
import { useAppStore } from '@/stores/app'
import { useECharts } from '@/composables/useECharts'
import type { EChartsOption } from 'echarts'

const { t } = useI18n()
const topologyStore = useTopologyStore()
const appStore = useAppStore()

const pieChartRef = ref<HTMLElement | null>(null)

const pieOptions = computed<EChartsOption>(() => {
  const r = topologyStore.redCount
  const y = topologyStore.yellowCount
  const g = topologyStore.greenCount
  const hasData = r + y + g > 0

  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [
      {
        type: 'pie',
        radius: ['52%', '76%'],
        center: ['50%', '50%'],
        avoidLabelOverlap: false,
        label: { show: false },
        emphasis: {
          label: { show: true, fontSize: 12, fontWeight: 'bold' },
        },
        data: hasData
          ? [
              { name: t('fiberColor.redCount'), value: r, itemStyle: { color: '#f56c6c' } },
              { name: t('fiberColor.yellowCount'), value: y, itemStyle: { color: '#e6a23c' } },
              { name: t('fiberColor.greenCount'), value: g, itemStyle: { color: '#67c23a' } },
            ]
          : [{ name: 'N/A', value: 1, itemStyle: { color: 'rgba(128,128,128,0.15)' } }],
        itemStyle: { borderRadius: 3, borderWidth: 2, borderColor: 'var(--fa-bg-secondary)' },
        animationDuration: 600,
      },
    ],
  }
})

useECharts(pieChartRef, pieOptions)

const lastUpdateLabel = computed(() => {
  if (!topologyStore.lastStatsUpdate) return '--'
  return new Date(topologyStore.lastStatsUpdate).toLocaleTimeString('zh-CN', { hour12: false })
})
</script>

<style scoped lang="scss">
.fiber-color-stats {
  border: 1px solid var(--fa-border-color);
  border-radius: 10px;
  background: var(--fa-bg-secondary);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;

  .panel-title {
    font-size: 13px;
    font-weight: 700;
    color: var(--fa-text-primary);
    letter-spacing: 0.3px;
  }

  .ws-indicator {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 9px;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    color: var(--fa-text-muted);
    padding: 2px 7px;
    border-radius: 10px;
    border: 1px solid var(--fa-border-color);

    .ws-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--fa-text-muted);
    }

    &.online {
      color: var(--fa-success);
      border-color: rgba(103, 194, 58, 0.35);

      .ws-dot {
        background: var(--fa-success);
        animation: ws-pulse 2s infinite;
      }
    }
  }
}

.stats-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.color-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;

  .color-card {
    display: flex;
    align-items: stretch;
    border-radius: 8px;
    border: 1px solid var(--fa-border-color);
    background: var(--fa-bg-primary);
    overflow: hidden;
    transition: transform 0.15s, box-shadow 0.15s;

    &:hover {
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
    }

    .color-bar {
      width: 4px;
      flex-shrink: 0;
    }

    .color-content {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 10px 6px;

      .color-value {
        font-size: 22px;
        font-weight: 800;
        font-family: 'JetBrains Mono', monospace;
        line-height: 1.2;
      }

      .color-label {
        font-size: 9px;
        color: var(--fa-text-muted);
        margin-top: 2px;
        white-space: nowrap;
      }
    }

    &.red {
      .color-bar { background: #f56c6c; }
      .color-value { color: #f56c6c; }
    }
    &.yellow {
      .color-bar { background: #e6a23c; }
      .color-value { color: #e6a23c; }
    }
    &.green {
      .color-bar { background: #67c23a; }
      .color-value { color: #67c23a; }
    }
  }
}

.pie-chart {
  height: 140px;
  min-height: 140px;
}

.stats-footer {
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding-top: 8px;
  border-top: 1px dashed var(--fa-border-color);

  .footer-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1px;

    .footer-value {
      font-size: 14px;
      font-weight: 700;
      font-family: 'JetBrains Mono', monospace;
      color: var(--fa-text-primary);

      &.alarm-num { color: var(--fa-warning); }
    }

    .footer-label {
      font-size: 9px;
      color: var(--fa-text-muted);
    }
  }

  .footer-divider {
    width: 1px;
    height: 24px;
    background: var(--fa-border-color);
  }
}

// 数字切换动画
.num-enter-active,
.num-leave-active {
  transition: all 0.25s ease;
}
.num-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.num-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

@keyframes ws-pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(103, 194, 58, 0.4); }
  50% { opacity: 0.7; box-shadow: 0 0 0 3px rgba(103, 194, 58, 0); }
}
</style>
