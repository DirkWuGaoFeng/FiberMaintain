<template>
  <div class="memory-view">
    <!-- 页头 -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">{{ $t('memory.title') }}</h2>
        <span class="page-desc">{{ $t('memory.description') }}</span>
      </div>
      <el-button type="danger" plain size="small" @click="handleCleanup">
        <el-icon><Delete /></el-icon> {{ $t('memory.cleanup') }}
      </el-button>
    </div>

    <div class="memory-content">
      <!-- 查询面板 -->
      <div class="query-panel">
        <div class="query-row">
          <el-input
            v-model="fiberId"
            :placeholder="$t('memory.fiberIdPlaceholder')"
            class="fiber-input"
            clearable
            @keydown.enter="handleQuery"
          >
            <template #prepend>{{ $t('memory.queryFiber') }}</template>
          </el-input>
          <div class="days-select">
            <span class="days-label">{{ $t('memory.days') }}</span>
            <el-select v-model="days" size="default" style="width: 90px">
              <el-option :value="7" label="7 天" />
              <el-option :value="30" label="30 天" />
              <el-option :value="60" label="60 天" />
              <el-option :value="90" label="90 天" />
            </el-select>
          </div>
          <el-button type="primary" :loading="loading" :disabled="!fiberId.trim()" @click="handleQuery">
            <el-icon><Search /></el-icon> {{ $t('common.search') }}
          </el-button>
        </div>

        <!-- 最新快照 -->
        <div v-if="latestSnapshot" class="latest-card">
          <div class="latest-title">{{ $t('memory.latestSnapshot') }}</div>
          <div class="latest-grid">
            <div class="latest-item">
              <span class="item-label">{{ $t('memory.spanloss') }}</span>
              <span class="item-value" :class="severityClass">{{ latestSnapshot.spanloss }} dB</span>
            </div>
            <div class="latest-item">
              <span class="item-label">{{ $t('memory.colorLabel') }}</span>
              <el-tag :type="colorType(latestSnapshot.color)" effect="dark" size="small">
                {{ latestSnapshot.color }}
              </el-tag>
            </div>
            <div class="latest-item">
              <span class="item-label">{{ $t('memory.createdAt') }}</span>
              <span class="item-value time">{{ formatTime(latestSnapshot.created_at) }}</span>
            </div>
            <div class="latest-item summary">
              <span class="item-label">{{ $t('memory.summary') }}</span>
              <span class="item-value">{{ latestSnapshot.summary || '—' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 趋势图 + 快照历史 -->
      <div class="data-area">
        <!-- 衰耗趋势图 -->
        <div class="trend-card">
          <div class="card-title">{{ $t('memory.trend') }}</div>
          <div ref="trendChartRef" class="trend-chart" />
        </div>

        <!-- 快照列表 -->
        <div class="snapshots-card">
          <div class="card-title">
            {{ $t('memory.snapshots') }}
            <el-tag size="small" type="info" effect="plain">{{ snapshots.length }}</el-tag>
          </div>

          <div v-if="loading" class="loading-state">
            <el-icon class="is-loading" :size="20"><Loading /></el-icon>
          </div>

          <div v-else-if="snapshots.length === 0" class="empty-state">
            {{ $t('memory.noSnapshots') }}
          </div>

          <el-scrollbar v-else class="snapshot-scroll">
            <div class="snapshot-list">
              <div
                v-for="(snap, idx) in snapshots"
                :key="idx"
                class="snapshot-item"
              >
                <span class="snap-color-dot" :class="snap.color.toLowerCase()" />
                <div class="snap-body">
                  <div class="snap-row">
                    <span class="snap-spanloss">{{ snap.spanloss }} dB</span>
                    <el-tag :type="colorType(snap.color)" size="small" effect="plain">{{ snap.color }}</el-tag>
                    <span class="snap-time">{{ formatTime(snap.created_at) }}</span>
                  </div>
                  <p v-if="snap.summary" class="snap-summary">{{ snap.summary }}</p>
                </div>
              </div>
            </div>
          </el-scrollbar>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 记忆管理页 — 光纤快照历史查询 + 趋势图 + 清理
 */
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { getSnapshots, getLatestSnapshot, cleanupMemory, type FiberSnapshot } from '@/api/memory'
import { useECharts } from '@/composables/useECharts'
import type { EChartsOption } from 'echarts'

const { t } = useI18n()

const fiberId = ref('')
const days = ref(30)
const loading = ref(false)
const snapshots = ref<FiberSnapshot[]>([])
const latestSnapshot = ref<FiberSnapshot | null>(null)

// ===== 趋势图 =====
const trendChartRef = ref<HTMLElement | null>(null)

const trendOptions = computed<EChartsOption>(() => {
  const data = [...snapshots.value].reverse()
  const times = data.map((s) => formatTime(s.created_at))
  const values = data.map((s) => s.spanloss)
  const colors = data.map((s) =>
    s.color === 'RED' ? '#f56c6c' : s.color === 'YELLOW' ? '#e6a23c' : '#67c23a',
  )

  return {
    tooltip: { trigger: 'axis' },
    grid: { top: 20, bottom: 24, left: 48, right: 16 },
    xAxis: { type: 'category', data: times, axisLabel: { fontSize: 9 } },
    yAxis: { type: 'value', name: 'dB', axisLabel: { fontSize: 9 } },
    series: [
      {
        type: 'line',
        data: values,
        smooth: true,
        lineStyle: { width: 2, color: '#409eff' },
        itemStyle: {
          color: (params: { dataIndex: number }) => colors[params.dataIndex] || '#409eff',
        },
        areaStyle: { color: 'rgba(64, 158, 255, 0.06)' },
        markLine: {
          silent: true,
          data: [
            { yAxis: 5.0, name: 'WARNING', lineStyle: { color: '#e6a23c', type: 'dashed' } },
            { yAxis: 8.0, name: 'CRITICAL', lineStyle: { color: '#f56c6c', type: 'dashed' } },
          ],
          label: { fontSize: 9 },
        },
      },
    ],
  }
})

useECharts(trendChartRef, trendOptions)

// ===== 操作 =====
async function handleQuery() {
  const id = fiberId.value.trim()
  if (!id) return

  loading.value = true
  try {
    const [snaps, latest] = await Promise.allSettled([
      getSnapshots(id, days.value),
      getLatestSnapshot(id),
    ])
    if (snaps.status === 'fulfilled') snapshots.value = snaps.value
    if (latest.status === 'fulfilled') latestSnapshot.value = latest.value
  } finally {
    loading.value = false
  }
}

async function handleCleanup() {
  try {
    await ElMessageBox.confirm(
      t('memory.cleanupConfirm', { days: 90 }),
      t('memory.cleanup'),
      { confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'), type: 'warning' },
    )
    const result = await cleanupMemory(90)
    ElMessage.success(t('memory.cleanupResult', { count: result.deleted }))
  } catch {
    // 取消
  }
}

function colorType(color: string): 'success' | 'warning' | 'danger' {
  if (color === 'RED') return 'danger'
  if (color === 'YELLOW') return 'warning'
  return 'success'
}

const severityClass = computed(() => {
  if (!latestSnapshot.value) return ''
  const v = latestSnapshot.value.spanloss
  if (v >= 8) return 'critical'
  if (v >= 5) return 'warning'
  return 'normal'
})

function formatTime(iso: string): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}
</script>

<style scoped lang="scss">
.memory-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  padding: 16px 20px;
  gap: 14px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;

  .header-left {
    display: flex;
    align-items: baseline;
    gap: 14px;

    .page-title {
      margin: 0;
      font-size: 16px;
      font-weight: 700;
      color: var(--fa-text-primary);
    }

    .page-desc {
      font-size: 12px;
      color: var(--fa-text-muted);
    }
  }
}

.memory-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

.query-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;

  .query-row {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;

    .fiber-input {
      width: 280px;
    }

    .days-select {
      display: flex;
      align-items: center;
      gap: 6px;

      .days-label {
        font-size: 12px;
        color: var(--fa-text-muted);
      }
    }
  }

  .latest-card {
    border: 1px solid var(--fa-border-color);
    border-radius: 10px;
    background: var(--fa-bg-secondary);
    padding: 12px 16px;

    .latest-title {
      font-size: 12px;
      font-weight: 700;
      color: var(--fa-text-secondary);
      margin-bottom: 10px;
    }

    .latest-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;

      .latest-item {
        display: flex;
        flex-direction: column;
        gap: 4px;

        .item-label {
          font-size: 10px;
          color: var(--fa-text-muted);
          text-transform: uppercase;
        }

        .item-value {
          font-size: 16px;
          font-weight: 700;
          color: var(--fa-text-primary);
          font-family: 'JetBrains Mono', monospace;

          &.normal { color: var(--fa-success); }
          &.warning { color: var(--fa-warning); }
          &.critical { color: var(--fa-danger); }
          &.time { font-size: 12px; font-weight: 500; }
        }

        &.summary .item-value {
          font-size: 12px;
          font-weight: 400;
          font-family: inherit;
          color: var(--fa-text-secondary);
          line-height: 1.5;
        }
      }
    }
  }
}

.data-area {
  flex: 1;
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 14px;
  min-height: 0;

  @media (max-width: 900px) {
    grid-template-columns: 1fr;
  }

  .trend-card, .snapshots-card {
    border: 1px solid var(--fa-border-color);
    border-radius: 10px;
    background: var(--fa-bg-secondary);
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    min-height: 0;

    .card-title {
      font-size: 12px;
      font-weight: 700;
      color: var(--fa-text-secondary);
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
  }

  .trend-chart {
    flex: 1;
    min-height: 180px;
  }

  .loading-state, .empty-state {
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 40px 0;
    font-size: 12px;
    color: var(--fa-text-muted);
  }

  .snapshot-scroll {
    flex: 1;
    min-height: 0;
  }

  .snapshot-list {
    display: flex;
    flex-direction: column;
    gap: 8px;

    .snapshot-item {
      display: flex;
      gap: 10px;
      padding: 10px 12px;
      border: 1px solid var(--fa-border-color);
      border-radius: 8px;
      transition: border-color 0.2s;

      &:hover {
        border-color: rgba(64, 158, 255, 0.4);
      }

      .snap-color-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        margin-top: 4px;
        flex-shrink: 0;

        &.green { background: #67c23a; }
        &.yellow { background: #e6a23c; }
        &.red { background: #f56c6c; animation: pulse 1.2s infinite; }
      }

      .snap-body {
        flex: 1;
        min-width: 0;

        .snap-row {
          display: flex;
          align-items: center;
          gap: 10px;

          .snap-spanloss {
            font-size: 14px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
            color: var(--fa-text-primary);
          }

          .snap-time {
            margin-left: auto;
            font-size: 10px;
            color: var(--fa-text-muted);
          }
        }

        .snap-summary {
          margin: 4px 0 0;
          font-size: 11px;
          color: var(--fa-text-secondary);
          line-height: 1.5;
        }
      }
    }
  }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
</style>
