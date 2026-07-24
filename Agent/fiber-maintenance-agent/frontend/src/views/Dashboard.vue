<template>
  <div style="padding: 24px; height: 100%; overflow-y: auto">
    <h2 style="margin-bottom: 16px">📊 光纤状态统计面板</h2>

    <!-- 概览卡片 -->
    <el-row :gutter="16" style="margin-bottom: 24px">
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>🔴 红色（紧急）</template>
          <div style="font-size: 36px; font-weight: bold; color: #e63946">
            {{ stats.red_count }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>🟡 黄色（关注）</template>
          <div style="font-size: 36px; font-weight: bold; color: #f4a261">
            {{ stats.yellow_count }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>📡 活跃告警</template>
          <div style="font-size: 36px; font-weight: bold; color: #457b9d">
            {{ stats.active_alarms }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>🔗 WS 状态</template>
          <div style="font-size: 18px; padding-top: 10px">
            <el-tag :type="wsConnected ? 'success' : 'danger'">
              {{ wsConnected ? '已连接' : '已断开（重连中）' }}
            </el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 趋势图 -->
    <el-card style="margin-bottom: 24px">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>📈 颜色趋势（最近 24h）</span>
          <el-button size="small" @click="fetchTrend(24)" :loading="trendLoading">刷新</el-button>
        </div>
      </template>
      <div ref="chartRef" style="height: 320px"></div>
    </el-card>

    <!-- 最近颜色变化 -->
    <el-card>
      <template #header>🔄 最近颜色变化事件</template>
      <el-table :data="recentChanges" max-height="300" size="small">
        <el-table-column prop="fiber_id" label="光纤 ID" width="100" />
        <el-table-column label="变化" width="160">
          <template #default="{ row }">
            <span>{{ colorEmoji(row.old_color) }} → {{ colorEmoji(row.new_color) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="timestamp" label="时间" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { useFiberStats } from '../composables/useFiberStats'
import { useTrendData } from '../composables/useTrendData'

const { stats, recentChanges, wsConnected } = useFiberStats()
const { points, loading: trendLoading, fetchTrend } = useTrendData()
const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

function colorEmoji(c: string) {
  return c === 'RED' ? '🔴' : c === 'YELLOW' ? '🟡' : '🟢'
}

function renderChart() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['红色', '黄色'] },
    xAxis: { type: 'category', data: points.value.map(p => p.timestamp.slice(11, 16)) },
    yAxis: { type: 'value' },
    series: [
      { name: '红色', type: 'line', data: points.value.map(p => p.red_count), smooth: true, itemStyle: { color: '#e63946' } },
      { name: '黄色', type: 'line', data: points.value.map(p => p.yellow_count), smooth: true, itemStyle: { color: '#f4a261' } },
    ],
  })
}

watch(points, () => nextTick(renderChart), { deep: true })
onMounted(() => { fetchTrend(24) })
</script>