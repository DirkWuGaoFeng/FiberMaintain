<template>
  <div class="dashboard-container">
    <header>
      <div class="brand">
        <svg viewBox="0 0 32 32" fill="none">
          <path d="M3 22 C11 22 11 10 19 10 H29" stroke="#3fd0ff" stroke-width="1.8"/>
          <path d="M3 16 H29" stroke="#4f8dff" stroke-width="1.8"/>
          <path d="M3 10 C11 10 11 22 19 22 H29" stroke="#2fd6a3" stroke-width="1.8"/>
          <circle cx="28" cy="16" r="2.6" fill="#3fd0ff">
            <animate attributeName="opacity" values="1;.3;1" dur="1.6s" repeatCount="indefinite"/>
          </circle>
        </svg>
        <div>
          <h1>统计面板</h1>
          <small>FIBER OPS · DASHBOARD</small>
        </div>
      </div>
      <router-link to="/" class="pill back-link">← 返回主面板</router-link>
    </header>

    <section class="stats-grid">
      <div class="stat-card red">
        <div class="stat-icon">🔴</div>
        <div class="stat-info">
          <label>红色连纤</label>
          <b>{{ stats.red_count || 0 }}</b>
          <small>紧急告警</small>
        </div>
      </div>
      <div class="stat-card yellow">
        <div class="stat-icon">🟡</div>
        <div class="stat-info">
          <label>黄色连纤</label>
          <b>{{ stats.yellow_count || 0 }}</b>
          <small>次要告警</small>
        </div>
      </div>
      <div class="stat-card green">
        <div class="stat-icon">🟢</div>
        <div class="stat-info">
          <label>绿色连纤</label>
          <b>{{ stats.green_count || 0 }}</b>
          <small>正常状态</small>
        </div>
      </div>
      <div class="stat-card total">
        <div class="stat-icon">📊</div>
        <div class="stat-info">
          <label>有颜色总计</label>
          <b>{{ stats.total_colored || 0 }}</b>
          <small>网元间连纤</small>
        </div>
      </div>
    </section>

    <section class="chart-section">
      <div class="panel">
        <div class="sec">红/黄趋势图 <span class="r">5min粒度 · 保留7天</span></div>
        <div ref="chartContainer" class="chart-container"></div>
      </div>
    </section>

    <section class="table-section">
      <div class="panel">
        <div class="sec">最近颜色变化事件</div>
        <el-table :data="recentChanges" style="width: 100%">
          <el-table-column prop="timestamp" label="时间" width="180">
            <template #default="{ row }">
              {{ new Date(row.timestamp).toLocaleString() }}
            </template>
          </el-table-column>
          <el-table-column prop="fiber_id" label="光纤ID" width="120"/>
          <el-table-column prop="old_color" label="原颜色" width="100">
            <template #default="{ row }">
              <span :class="'dot-' + row.old_color"></span>
              {{ colorMap[row.old_color] || row.old_color }}
            </template>
          </el-table-column>
          <el-table-column prop="new_color" label="新颜色" width="100">
            <template #default="{ row }">
              <span :class="'dot-' + row.new_color"></span>
              {{ colorMap[row.new_color] || row.new_color }}
            </template>
          </el-table-column>
          <el-table-column label="变化" width="120">
            <template #default="{ row }">
              <span class="transition">{{ colorMap[row.old_color] }} → {{ colorMap[row.new_color] }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useFiberStats } from '../composables/useFiberStats'
import { useTrendData } from '../composables/useTrendData'
import * as echarts from 'echarts'

const { stats, recentChanges } = useFiberStats()
const { points, fetchTrend } = useTrendData()

const chartContainer = ref(null)
let chartInstance = null

const colorMap = { red: '红色', yellow: '黄色', green: '绿色' }

function initChart() {
  if (!chartContainer.value) return
  chartInstance = echarts.init(chartContainer.value, 'dark')
  updateChart()
}

function updateChart() {
  if (!chartInstance) return
  const times = points.value.map(p => p.timestamp)
  const redData = points.value.map(p => p.red_count)
  const yellowData = points.value.map(p => p.yellow_count)

  const option = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { data: ['红色', '黄色'], textStyle: { color: '#d0dfef' } },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: times, axisLabel: { color: '#5b7391' } },
    yAxis: { type: 'value', axisLabel: { color: '#5b7391' } },
    series: [
      { name: '红色', type: 'line', data: redData, smooth: true, itemStyle: { color: '#ff5257' }, areaStyle: { color: 'rgba(255,82,87,0.2)' } },
      { name: '黄色', type: 'line', data: yellowData, smooth: true, itemStyle: { color: '#ffb224' }, areaStyle: { color: 'rgba(255,178,36,0.2)' } }
    ]
  }
  chartInstance.setOption(option)
}

onMounted(async () => {
  await fetchTrend(24)
  initChart()
})

onUnmounted(() => {
  if (chartInstance) chartInstance.dispose()
})

watch(points, () => updateChart(), { deep: true })
</script>

<style scoped>
.dashboard-container { height: 100vh; display: flex; flex-direction: column; background: var(--bg0); }
header { height: 54px; flex: none; display: flex; align-items: center; gap: 16px; padding: 0 16px; border-bottom: 1px solid var(--line); background: linear-gradient(180deg, #0d1a2e, #0a1424); }
.brand { display: flex; align-items: center; gap: 11px; }
.brand svg { width: 30px; height: 30px; }
.brand h1 { font-size: 16px; font-weight: 700; letter-spacing: .04em; }
.brand small { display: block; font-family: var(--disp); font-size: 10px; letter-spacing: .28em; color: var(--tx3); font-weight: 600; }
.back-link { margin-left: auto; cursor: pointer; color: var(--cyan); border-color: rgba(63,208,255,.4); background: rgba(63,208,255,.08); text-decoration: none; transition: .2s; }
.back-link:hover { background: rgba(63,208,255,.18); }
.stats-grid { flex: none; display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; padding: 20px; }
.stat-card { display: flex; align-items: center; gap: 16px; padding: 20px; border-radius: 8px; border: 1px solid var(--line); background: var(--panel); transition: transform .2s; }
.stat-card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,.3); }
.stat-icon { font-size: 36px; }
.stat-info label { display: block; font-size: 12px; color: var(--tx2); letter-spacing: .1em; }
.stat-info b { display: block; font-family: var(--disp); font-weight: 700; font-size: 32px; line-height: 1.1; margin: 4px 0; }
.stat-info small { font-size: 11px; font-family: var(--mono); color: var(--tx3); }
.stat-card.red { background: linear-gradient(180deg, rgba(255,82,87,.16), rgba(255,82,87,.04)); border-color: rgba(255,82,87,.4); }
.stat-card.red b { color: var(--red); text-shadow: 0 0 18px rgba(255,82,87,.5); }
.stat-card.yellow { background: linear-gradient(180deg, rgba(255,178,36,.14), rgba(255,178,36,.04)); border-color: rgba(255,178,36,.4); }
.stat-card.yellow b { color: var(--amber); text-shadow: 0 0 18px rgba(255,178,36,.45); }
.stat-card.green { background: linear-gradient(180deg, rgba(47,214,163,.14), rgba(47,214,163,.04)); border-color: rgba(47,214,163,.4); }
.stat-card.green b { color: var(--green); }
.stat-card.total { background: linear-gradient(180deg, rgba(63,208,255,.12), rgba(63,208,255,.03)); border-color: rgba(63,208,255,.35); }
.stat-card.total b { color: var(--cyan); }
.chart-section { flex: 1; min-height: 0; padding: 0 20px 20px; }
.chart-container { height: 400px; }
.table-section { flex: none; padding: 0 20px 20px; }
.dot-red, .dot-yellow, .dot-green { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
.dot-red { background: var(--red); box-shadow: 0 0 6px var(--red); }
.dot-yellow { background: var(--amber); box-shadow: 0 0 5px var(--amber); }
.dot-green { background: var(--green); }
.transition { font-family: var(--mono); font-size: 12px; color: var(--tx2); }
</style>
