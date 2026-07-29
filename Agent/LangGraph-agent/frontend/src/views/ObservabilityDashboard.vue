<template>
  <div class="obs-container">
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
          <h1>Agent 运行看板</h1>
          <small>LANGGRAPH AGENT · OBSERVABILITY</small>
        </div>
      </div>
      <div class="header-actions">
        <el-button size="small" @click="fetchMetrics" :loading="loading">刷新</el-button>
        <router-link to="/" class="pill back-link">← 返回主面板</router-link>
      </div>
    </header>

    <div class="content">
      <section class="metrics-grid">
        <div class="metric-card">
          <div class="metric-label">总请求数</div>
          <div class="metric-value">{{ metrics.totalRequests || 0 }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">平均响应时间</div>
          <div class="metric-value">{{ (metrics.avgResponseTime || 0).toFixed(0) }}ms</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">成功率</div>
          <div class="metric-value">{{ ((metrics.successRate || 0) * 100).toFixed(1) }}%</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">活跃会话</div>
          <div class="metric-value">{{ metrics.activeSessions || 0 }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">工具调用次数</div>
          <div class="metric-value">{{ metrics.toolCalls || 0 }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Token 消耗</div>
          <div class="metric-value">{{ formatNumber(metrics.totalTokens || 0) }}</div>
        </div>
      </section>

      <section class="panel traces-panel">
        <div class="sec">链路追踪 <span class="r">最近 {{ traces.length }} 条</span></div>
        <el-table :data="traces" style="width: 100%" @row-click="showTraceDetail">
          <el-table-column prop="traceId" label="Trace ID" width="200">
            <template #default="{ row }">
              <span class="trace-id">{{ row.traceId?.slice(0, 16) }}...</span>
            </template>
          </el-table-column>
          <el-table-column prop="operation" label="操作" width="200"/>
          <el-table-column prop="duration" label="耗时" width="100">
            <template #default="{ row }">
              <span :class="{ slow: row.duration > 5000 }">{{ row.duration }}ms</span>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'ok' ? 'success' : row.status === 'error' ? 'danger' : 'warning'" size="small">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="timestamp" label="时间" width="180">
            <template #default="{ row }">
              {{ new Date(row.timestamp).toLocaleString() }}
            </template>
          </el-table-column>
          <el-table-column prop="agentName" label="Agent" width="150"/>
        </el-table>
      </section>

      <section v-if="selectedTrace" class="panel detail-panel">
        <div class="sec">链路详情
          <button class="close-btn" @click="selectedTrace = null">✕</button>
        </div>
        <div class="detail-content">
          <div class="detail-row">
            <label>Trace ID:</label>
            <span>{{ selectedTrace.traceId }}</span>
          </div>
          <div class="detail-row">
            <label>操作:</label>
            <span>{{ selectedTrace.operation }}</span>
          </div>
          <div class="detail-row">
            <label>耗时:</label>
            <span>{{ selectedTrace.duration }}ms</span>
          </div>
          <div class="detail-row">
            <label>状态:</label>
            <el-tag :type="selectedTrace.status === 'ok' ? 'success' : 'danger'" size="small">{{ selectedTrace.status }}</el-tag>
          </div>
          <div class="detail-row" v-if="selectedTrace.spans && selectedTrace.spans.length">
            <label>Spans:</label>
            <div class="spans-list">
              <div v-for="(span, idx) in selectedTrace.spans" :key="idx" class="span-item">
                <span class="span-name">{{ span.name }}</span>
                <span class="span-dur">{{ span.duration }}ms</span>
                <span v-if="span.error" class="span-err">{{ span.error }}</span>
              </div>
            </div>
          </div>
          <div class="detail-row" v-if="selectedTrace.metadata">
            <label>元数据:</label>
            <pre class="metadata">{{ JSON.stringify(selectedTrace.metadata, null, 2) }}</pre>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getObsMetrics, getObsTraces, getObsTraceDetail } from '../api/index.js'

const metrics = ref({})
const traces = ref([])
const selectedTrace = ref(null)
const loading = ref(false)

function formatNumber(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n)
}

async function fetchMetrics() {
  loading.value = true
  try {
    const [metricsResp, tracesResp] = await Promise.all([getObsMetrics(), getObsTraces(20)])
    metrics.value = metricsResp.data || {}
    traces.value = tracesResp.data?.traces || []
  } catch (e) { console.error('Failed to fetch metrics:', e) }
  loading.value = false
}

async function showTraceDetail(row) {
  try {
    const { data } = await getObsTraceDetail(row.traceId)
    selectedTrace.value = data.trace || row
  } catch (e) {
    selectedTrace.value = row
  }
}

onMounted(() => fetchMetrics())
</script>

<style scoped>
.obs-container { height: 100vh; display: flex; flex-direction: column; background: var(--bg0); }
header { height: 54px; flex: none; display: flex; align-items: center; gap: 16px; padding: 0 16px; border-bottom: 1px solid var(--line); background: linear-gradient(180deg, #0d1a2e, #0a1424); }
.brand { display: flex; align-items: center; gap: 11px; }
.brand svg { width: 30px; height: 30px; }
.brand h1 { font-size: 16px; font-weight: 700; letter-spacing: .04em; }
.brand small { display: block; font-family: var(--disp); font-size: 10px; letter-spacing: .28em; color: var(--tx3); font-weight: 600; }
.header-actions { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.back-link { cursor: pointer; color: var(--cyan); border-color: rgba(63,208,255,.4); background: rgba(63,208,255,.08); text-decoration: none; transition: .2s; }
.back-link:hover { background: rgba(63,208,255,.18); }
.content { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 16px; padding: 16px; overflow-y: auto; }
.metrics-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; }
.metric-card { padding: 16px; border-radius: 8px; border: 1px solid var(--line); background: var(--panel); text-align: center; transition: transform .2s; }
.metric-card:hover { transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,.3); }
.metric-label { font-size: 11px; color: var(--tx3); font-family: var(--mono); letter-spacing: .08em; margin-bottom: 8px; }
.metric-value { font-family: var(--disp); font-weight: 700; font-size: 24px; color: var(--cyan); }
.traces-panel { flex: none; }
.trace-id { font-family: var(--mono); font-size: 11px; color: var(--cyan); }
.slow { color: var(--red); font-weight: 600; }
.detail-panel { flex: none; }
.close-btn { float: right; background: transparent; border: none; color: var(--tx3); cursor: pointer; font-size: 14px; padding: 2px 8px; }
.close-btn:hover { color: var(--red); }
.detail-content { padding: 12px 16px; }
.detail-row { display: flex; gap: 12px; padding: 6px 0; font-size: 13px; border-bottom: 1px solid rgba(255,255,255,.04); }
.detail-row label { flex: none; width: 80px; color: var(--tx3); font-family: var(--mono); font-size: 11px; }
.detail-row span { color: var(--tx); }
.spans-list { display: flex; flex-direction: column; gap: 4px; }
.span-item { display: flex; gap: 10px; align-items: center; padding: 4px 8px; border-radius: 4px; background: rgba(63,208,255,.04); font-size: 12px; }
.span-name { font-family: var(--mono); color: var(--tx2); }
.span-dur { font-family: var(--mono); font-size: 10px; color: var(--cyan); margin-left: auto; }
.span-err { font-size: 10px; color: var(--red); }
.metadata { background: #0a1524; border: 1px solid #1c3149; border-radius: 6px; padding: 10px; font-family: var(--mono); font-size: 11px; color: var(--tx2); overflow-x: auto; max-height: 200px; }
@media (max-width: 1200px) { .metrics-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 768px) { .metrics-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
