<template>
  <div class="obs-container">
    <!-- 顶部状态栏 -->
    <header class="obs-header">
      <div class="brand">
        <svg viewBox="0 0 32 32" fill="none" width="28" height="28">
          <path d="M3 22 C11 22 11 10 19 10 H29" stroke="#3fd0ff" stroke-width="1.8"/>
          <path d="M3 16 H29" stroke="#4f8dff" stroke-width="1.8"/>
          <path d="M3 10 C11 10 11 22 19 22 H29" stroke="#2fd6a3" stroke-width="1.8"/>
          <circle cx="28" cy="16" r="2.6" fill="#3fd0ff">
            <animate attributeName="opacity" values="1;.3;1" dur="1.6s" repeatCount="indefinite"/>
          </circle>
        </svg>
        <div>
          <h1>Agent 运行看板</h1>
          <small>OBSERVABILITY DASHBOARD · §17.6.2</small>
        </div>
      </div>
      <div class="header-actions">
        <span class="pill" :class="system.backend_up ? 'ok' : 'err'">
          <i class="dot"></i>{{ system.backend_up ? '后端在线' : '后端离线' }}
        </span>
        <span class="pill lvl" :class="'l' + degradationLevel">
          {{ levelLabel }}
        </span>
        <span class="pill model">{{ system.llm_model }}</span>
        <button class="refresh-btn" @click="fetchAll" :disabled="loading">
          <svg viewBox="0 0 24 24" width="16" height="16" :class="{ spin: loading }">
            <path d="M17.65 6.35A7.96 7.96 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z" fill="currentColor"/>
          </svg>
          刷新
        </button>
        <router-link to="/" class="back-link">← 返回主面板</router-link>
        <router-link to="/admin/knowledge" class="back-link rag-link"> RAG 管理</router-link>
      </div>
    </header>

    <!-- 指标卡片行 -->
    <section class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-label">当前状态</div>
        <div class="kpi-value" :class="'level-' + degradationLevel">{{ levelLabel }}</div>
        <div class="kpi-sub">降级级别: {{ degradationLevel }} / 4</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">今日请求</div>
        <div class="kpi-value cyan">{{ totalRequests }}</div>
        <div class="kpi-sub">较昨日 {{ requestDelta }}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">P50 / P95 / P99 延迟</div>
        <div class="kpi-value amber">{{ latencyP50 }}<small>ms</small></div>
        <div class="kpi-sub">{{ latencyP95 }}ms / {{ latencyP99 }}ms</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">错误率 (1min)</div>
        <div class="kpi-value" :class="errorRate > 5 ? 'red' : 'green'">{{ errorRate.toFixed(1) }}%</div>
        <div class="kpi-sub">{{ errorCount }} 个错误 / {{ totalRequests1m }} 请求</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Embedding 模型</div>
        <div class="kpi-value small-text">{{ system.embedding_model || 'N/A' }}</div>
        <div class="kpi-sub">{{ system.offline_mode ? '离线模式' : '在线模式' }}</div>
      </div>
    </section>

    <!-- 主内容区 -->
    <main class="obs-main">
      <!-- 左列: Sub-Agent 分布 + Token 消耗 -->
      <div class="obs-left">
        <!-- Sub-Agent 调用分布 -->
        <div class="panel">
          <div class="panel-head">Sub-Agent 调用分布</div>
          <div class="agent-bars">
            <div v-for="agent in agentStats" :key="agent.name" class="agent-bar-row">
              <span class="agent-name">{{ agent.name }}</span>
              <div class="agent-bar-bg">
                <div class="agent-bar" :style="{ width: agent.pct + '%', background: agent.color }"></div>
              </div>
              <span class="agent-count">{{ agent.count }}</span>
            </div>
          </div>
        </div>

        <!-- Token 消耗趋势 -->
        <div class="panel">
          <div class="panel-head">Token 消耗趋势 <span class="hint">（最近 10 次刷新）</span></div>
          <div class="token-chart" v-if="tokenHistory.length >= 2">
            <canvas ref="tokenCanvas" width="400" height="180"></canvas>
          </div>
          <div class="token-chart token-empty" v-else>
            <span>等待数据积累中...（需至少 2 次刷新）</span>
          </div>
        </div>

        <!-- 延迟分布 -->
        <div class="panel">
          <div class="panel-head">请求延迟分布</div>
          <div class="latency-bars">
            <div v-for="item in latencyDistribution" :key="item.label" class="lat-row">
              <span class="lat-label">{{ item.label }}</span>
              <div class="lat-bar-bg">
                <div class="lat-bar" :style="{ width: item.pct + '%', background: item.color }"></div>
              </div>
              <span class="lat-val">{{ item.value }}ms</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右列: Trace 记录 -->
      <div class="obs-right">
        <div class="panel trace-panel">
          <div class="panel-head">
            最近 Trace 记录
            <span class="trace-count">{{ traces.length }} 条</span>
          </div>
          <div class="trace-table">
            <div class="trace-header">
              <span class="th trace-id">Trace ID</span>
              <span class="th operation">操作</span>
              <span class="th status">状态</span>
              <span class="th duration">耗时</span>
            </div>
            <div v-for="t in traces" :key="t.trace_id" class="trace-row"
                 @click="showTraceDetail(t.trace_id)">
              <span class="td trace-id mono">{{ t.trace_id?.substring(0, 12) }}…</span>
              <span class="td operation">{{ t.operation }}</span>
              <span class="td status">
                <span class="status-badge" :class="t.status">{{ t.status }}</span>
              </span>
              <span class="td duration mono">{{ formatDuration(t.start_time, t.end_time) }}</span>
            </div>
            <div v-if="traces.length === 0" class="trace-empty">暂无 Trace 记录</div>
          </div>
        </div>

        <!-- Trace 详情弹窗 -->
        <div v-if="selectedTrace" class="trace-detail-overlay" @click.self="selectedTrace = null">
          <div class="trace-detail-modal">
            <div class="modal-head">
              <span>Trace: {{ selectedTrace.trace_id }}</span>
              <button @click="selectedTrace = null">✕</button>
            </div>
            <div class="span-list">
              <div v-for="s in selectedTrace.spans" :key="s.span_id" class="span-row">
                <span class="span-op">{{ s.operation }}</span>
                <span class="span-status" :class="s.status">{{ s.status }}</span>
                <span class="span-dur">{{ s.duration_ms?.toFixed(1) }}ms</span>
              </div>
              <div v-if="!selectedTrace.spans?.length" class="span-empty">无 Span 数据</div>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { getObsMetrics, getObsTraces, getObsTraceDetail } from '../api/index.js'

const loading = ref(false)
const metrics = ref({ counters: {}, latencies: {} })
const system = ref({ backend_up: false, offline_mode: false, llm_model: '', embedding_model: '', version: '' })
const traces = ref([])
const selectedTrace = ref(null)
const tokenCanvas = ref(null)
const tokenHistory = ref([])

// 降级级别计算
const degradationLevel = computed(() => {
  if (!system.value.backend_up) return system.value.offline_mode ? 4 : 3
  const counters = metrics.value.counters || {}
  const errors = (counters.trace_error || 0)
  if (errors > 10) return 2
  if (errors > 5) return 1
  return 0
})

const levelLabel = computed(() => {
  const labels = ['L1 正常', 'L2 模型降级', 'L3 规则兜底', 'L4 纯知识']
  return labels[degradationLevel.value] || 'L1 正常'
})

const totalRequests = computed(() => {
  return Object.values(metrics.value.counters || {}).reduce((a, b) => a + b, 0)
})

const requestDelta = computed(() => {
  const h = tokenHistory.value
  if (h.length < 2) return '—'
  const prev = h[h.length - 2]?.total || 0
  const curr = totalRequests.value
  const diff = curr - prev
  return diff >= 0 ? `+${diff}` : `${diff}`
})

const totalRequests1m = computed(() => totalRequests.value)

const errorCount = computed(() => (metrics.value.counters || {}).trace_error || 0)

const errorRate = computed(() => {
  const total = totalRequests1m.value || 1
  return (errorCount.value / total) * 100
})

const latencyP50 = computed(() => {
  const lats = metrics.value.latencies || {}
  for (const key of Object.keys(lats)) {
    return lats[key]?.p50?.toFixed(0) || '0'
  }
  return '0'
})

const latencyP95 = computed(() => {
  const lats = metrics.value.latencies || {}
  for (const key of Object.keys(lats)) {
    return lats[key]?.p95?.toFixed(0) || '0'
  }
  return '0'
})

const latencyP99 = computed(() => {
  const lats = metrics.value.latencies || {}
  for (const key of Object.keys(lats)) {
    return lats[key]?.max?.toFixed(0) || '0'
  }
  return '0'
})

// Sub-Agent 分布
const agentNames = ['topology-analyst', 'data-collector', 'analysis-expert', 'report-generator', 'knowledge-assistant']
const agentColors = ['#a78bfa', '#3fd0ff', '#4f8dff', '#2fd6a3', '#ffb224']
const agentStats = computed(() => {
  const counters = metrics.value.counters || {}
  const values = agentNames.map(name => ({
    name,
    count: counters[`agent_${name}`] || counters[`subagent_${name}`] || 0,
    color: agentColors[agentNames.indexOf(name)]
  }))
  const max = Math.max(...values.map(v => v.count), 1)
  return values.map(v => ({ ...v, pct: (v.count / max) * 100 }))
})

// 延迟分布
const latencyDistribution = computed(() => {
  const lats = metrics.value.latencies || {}
  const entries = Object.entries(lats)
  if (entries.length === 0) {
    return [
      { label: 'P50', value: 0, pct: 0, color: '#2fd6a3' },
      { label: 'P95', value: 0, pct: 0, color: '#ffb224' },
      { label: 'P99', value: 0, pct: 0, color: '#ff5257' },
    ]
  }
  const first = entries[0][1]
  const max = first?.max || 1
  return [
    { label: 'P50', value: (first?.p50 || 0).toFixed(0), pct: ((first?.p50 || 0) / max) * 100, color: '#2fd6a3' },
    { label: 'P95', value: (first?.p95 || 0).toFixed(0), pct: ((first?.p95 || 0) / max) * 100, color: '#ffb224' },
    { label: 'P99', value: (first?.max || 0).toFixed(0), pct: 100, color: '#ff5257' },
  ]
})

function formatDuration(start, end) {
  if (!start || !end) return '—'
  const ms = (end - start) * 1000
  return ms < 1000 ? ms.toFixed(0) + 'ms' : (ms / 1000).toFixed(1) + 's'
}

async function showTraceDetail(traceId) {
  try {
    const { data } = await getObsTraceDetail(traceId)
    selectedTrace.value = data
  } catch (e) {
    console.error('Trace detail error:', e)
  }
}

async function fetchAll() {
  loading.value = true
  try {
    const [metricsRes, tracesRes] = await Promise.all([
      getObsMetrics().catch(() => ({ data: { metrics: {}, system: {} } })),
      getObsTraces(20).catch(() => ({ data: { traces: [] } })),
    ])
    metrics.value = metricsRes.data.metrics || { counters: {}, latencies: {} }
    system.value = metricsRes.data.system || system.value
    traces.value = tracesRes.data.traces || []

    // Token history tracking
    tokenHistory.value.push({ total: totalRequests.value, time: Date.now() })
    if (tokenHistory.value.length > 10) tokenHistory.value.shift()
    nextTick(() => drawTokenChart())
  } catch (e) {
    console.error('Fetch error:', e)
  }
  loading.value = false
}

function drawTokenChart() {
  const canvas = tokenCanvas.value
  if (!canvas || tokenHistory.value.length < 2) return
  const ctx = canvas.getContext('2d')
  const w = canvas.clientWidth
  const h = canvas.clientHeight
  const dpr = window.devicePixelRatio || 1
  canvas.width = w * dpr
  canvas.height = h * dpr
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)

  const data = tokenHistory.value.map(h => h.total)
  const max = Math.max(...data, 1) * 1.2
  const n = data.length
  const padL = 36, padR = 8, padT = 12, padB = 24
  const X = i => padL + (w - padL - padR) * i / (n - 1)
  const Y = v => padT + (h - padT - padB) * (1 - v / max)

  // Grid
  ctx.strokeStyle = 'rgba(79,141,255,.12)'
  ctx.font = '9px JetBrains Mono'
  ctx.fillStyle = '#5b7391'
  for (let g = 0; g <= 3; g++) {
    const v = max * g / 3
    ctx.beginPath(); ctx.moveTo(padL, Y(v)); ctx.lineTo(w - padR, Y(v)); ctx.stroke()
    ctx.fillText(Math.round(v).toString(), 4, Y(v) + 3)
  }

  // Line + fill
  ctx.beginPath()
  data.forEach((v, i) => { i === 0 ? ctx.moveTo(X(i), Y(v)) : ctx.lineTo(X(i), Y(v)) })
  ctx.strokeStyle = '#3fd0ff'
  ctx.lineWidth = 2
  ctx.stroke()
  ctx.lineTo(X(n - 1), h - padB)
  ctx.lineTo(padL, h - padB)
  ctx.closePath()
  const grad = ctx.createLinearGradient(0, padT, 0, h - padB)
  grad.addColorStop(0, 'rgba(63,208,255,.3)')
  grad.addColorStop(1, 'rgba(63,208,255,0)')
  ctx.fillStyle = grad
  ctx.fill()

  // Dots
  data.forEach((v, i) => {
    ctx.beginPath()
    ctx.arc(X(i), Y(v), 3, 0, Math.PI * 2)
    ctx.fillStyle = '#3fd0ff'
    ctx.fill()
  })
}

let timer = null
onMounted(() => {
  fetchAll()
  timer = setInterval(fetchAll, 15000) // 15s 自动刷新
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.obs-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #0a1424;
  color: #c9d9ef;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  overflow-y: auto;
}

.obs-header {
  height: 54px;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 16px;
  border-bottom: 1px solid #1a2a40;
  background: linear-gradient(180deg, #0d1a2e, #0a1424);
  flex-shrink: 0;
}

.brand { display: flex; align-items: center; gap: 11px; }
.brand h1 { font-size: 16px; font-weight: 700; letter-spacing: .04em; margin: 0; }
.brand small { font-size: 10px; letter-spacing: .28em; color: #5b7391; font-weight: 600; }

.header-actions { margin-left: auto; display: flex; align-items: center; gap: 8px; }

.pill {
  font-size: 11px; font-family: 'JetBrains Mono', monospace;
  padding: 3px 10px; border-radius: 4px; border: 1px solid #1a2a40;
  display: flex; align-items: center; gap: 5px;
}
.pill .dot { width: 7px; height: 7px; border-radius: 50%; }
.pill.ok .dot { background: #2fd6a3; box-shadow: 0 0 6px #2fd6a3; }
.pill.err .dot { background: #ff5257; box-shadow: 0 0 6px #ff5257; }
.pill.model { color: #3fd0ff; border-color: rgba(63,208,255,.4); }
.pill.lvl.l0 { color: #2fd6a3; border-color: rgba(47,214,163,.4); }
.pill.lvl.l1 { color: #ffb224; border-color: rgba(255,178,36,.4); }
.pill.lvl.l2 { color: #ff8a50; border-color: rgba(255,138,80,.4); }
.pill.lvl.l3, .pill.lvl.l4 { color: #ff5257; border-color: rgba(255,82,87,.4); }

.refresh-btn {
  background: rgba(63,208,255,.12); border: 1px solid rgba(63,208,255,.4);
  color: #3fd0ff; padding: 4px 12px; border-radius: 4px; cursor: pointer;
  font-size: 11px; display: flex; align-items: center; gap: 5px;
  transition: .2s;
}
.refresh-btn:hover { background: rgba(63,208,255,.2); }
.refresh-btn:disabled { opacity: .5; cursor: not-allowed; }
.refresh-btn svg.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.back-link {
  color: #5b7391; font-size: 11px; text-decoration: none;
  margin-left: 8px; transition: .2s;
}
.back-link:hover { color: #3fd0ff; }

/* KPI Cards */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  padding: 12px 16px;
  flex-shrink: 0;
}

.kpi-card {
  background: linear-gradient(180deg, rgba(14,30,52,.9), rgba(10,20,36,.9));
  border: 1px solid #1a2a40;
  border-radius: 8px;
  padding: 14px 16px;
}

.kpi-label { font-size: 11px; color: #5b7391; letter-spacing: .08em; margin-bottom: 6px; }
.kpi-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 28px; font-weight: 700;
  line-height: 1.1;
}
.kpi-value small { font-size: 14px; font-weight: 400; color: #5b7391; margin-left: 2px; }
.kpi-value.cyan { color: #3fd0ff; }
.kpi-value.amber { color: #ffb224; }
.kpi-value.green { color: #2fd6a3; }
.kpi-value.red { color: #ff5257; }
.kpi-value.level-0 { color: #2fd6a3; }
.kpi-value.level-1 { color: #ffb224; }
.kpi-value.level-2 { color: #ff8a50; }
.kpi-value.level-3, .kpi-value.level-4 { color: #ff5257; }
.kpi-value.small-text { font-size: 14px; word-break: break-all; }
.kpi-sub { font-size: 10px; color: #5b7391; font-family: 'JetBrains Mono', monospace; margin-top: 4px; }

/* Main layout */
.obs-main {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 0 16px 12px;
  overflow: visible;
}

.obs-left, .obs-right {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  overflow-y: auto;
}

.panel {
  background: linear-gradient(180deg, rgba(14,30,52,.85), rgba(10,20,36,.85));
  border: 1px solid #1a2a40;
  border-radius: 8px;
  overflow: hidden;
}

.panel-head {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  color: #8ba3c2;
  border-bottom: 1px solid #1a2a40;
  letter-spacing: .05em;
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-head .hint { font-weight: 400; color: #5b7391; font-size: 10px; }

/* Agent bars */
.agent-bars { padding: 10px 14px; }
.agent-bar-row {
  display: grid;
  grid-template-columns: 140px 1fr 40px;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.agent-name { font-size: 11px; font-family: 'JetBrains Mono', monospace; color: #8ba3c2; }
.agent-bar-bg { height: 14px; background: #0a1524; border-radius: 4px; overflow: hidden; border: 1px solid #16283f; }
.agent-bar { height: 100%; border-radius: 3px; transition: width .6s ease; }
.agent-count { font-size: 11px; font-family: 'JetBrains Mono', monospace; color: #5b7391; text-align: right; }

/* Token chart */
.token-chart { padding: 8px; }
.token-chart canvas { width: 100%; height: 180px; }
.token-empty { display: flex; align-items: center; justify-content: center; height: 180px; color: #5b7391; font-size: 12px; }

/* Latency bars */
.latency-bars { padding: 10px 14px; }
.lat-row {
  display: grid;
  grid-template-columns: 36px 1fr 50px;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.lat-label { font-size: 11px; font-family: 'JetBrains Mono', monospace; color: #8ba3c2; }
.lat-bar-bg { height: 12px; background: #0a1524; border-radius: 4px; overflow: hidden; border: 1px solid #16283f; }
.lat-bar { height: 100%; border-radius: 3px; transition: width .6s ease; }
.lat-val { font-size: 11px; font-family: 'JetBrains Mono', monospace; color: #5b7391; text-align: right; }

/* Trace panel */
.trace-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.trace-count { font-size: 10px; color: #5b7391; font-weight: 400; }

.trace-table { flex: 1; overflow-y: auto; }
.trace-header {
  display: grid;
  grid-template-columns: 140px 1fr 70px 70px;
  gap: 8px;
  padding: 8px 14px;
  font-size: 10px;
  color: #5b7391;
  letter-spacing: .1em;
  border-bottom: 1px solid #1a2a40;
  position: sticky;
  top: 0;
  background: #0b1728;
}
.trace-row {
  display: grid;
  grid-template-columns: 140px 1fr 70px 70px;
  gap: 8px;
  padding: 7px 14px;
  font-size: 11px;
  cursor: pointer;
  transition: .15s;
  border-bottom: 1px solid rgba(26,42,64,.5);
}
.trace-row:hover { background: rgba(63,208,255,.06); }
.td, .th { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mono { font-family: 'JetBrains Mono', monospace; }
.trace-id { color: #3fd0ff; }
.operation { color: #8ba3c2; }
.status-badge {
  font-size: 10px; padding: 1px 6px; border-radius: 3px;
  font-family: 'JetBrains Mono', monospace;
}
.status-badge.ok { color: #2fd6a3; background: rgba(47,214,163,.12); border: 1px solid rgba(47,214,163,.3); }
.status-badge.error { color: #ff5257; background: rgba(255,82,87,.12); border: 1px solid rgba(255,82,87,.3); }
.duration { color: #5b7391; font-family: 'JetBrains Mono', monospace; text-align: right; }
.trace-empty { padding: 24px; text-align: center; color: #5b7391; font-size: 12px; }

/* Trace detail modal */
.trace-detail-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.6);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.trace-detail-modal {
  background: #0d1a2e; border: 1px solid #1a2a40; border-radius: 8px;
  width: 520px; max-height: 400px; overflow: hidden;
  box-shadow: 0 12px 40px rgba(0,0,0,.6);
}
.modal-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid #1a2a40;
  font-size: 13px; font-family: 'JetBrains Mono', monospace; color: #3fd0ff;
}
.modal-head button {
  background: none; border: none; color: #5b7391; cursor: pointer;
  font-size: 16px; transition: .2s;
}
.modal-head button:hover { color: #ff5257; }

.span-list { padding: 8px 16px; max-height: 340px; overflow-y: auto; }
.span-row {
  display: grid; grid-template-columns: 1fr 70px 70px; gap: 8px;
  padding: 6px 0; border-bottom: 1px solid rgba(26,42,64,.5); font-size: 11px;
}
.span-op { color: #8ba3c2; }
.span-status { font-family: 'JetBrains Mono', monospace; font-size: 10px; }
.span-status.ok { color: #2fd6a3; }
.span-status.error { color: #ff5257; }
.span-dur { font-family: 'JetBrains Mono', monospace; color: #5b7391; text-align: right; }
.span-empty { padding: 20px; text-align: center; color: #5b7391; font-size: 12px; }

.rag-link { color: #2fd6a3; }
.rag-link:hover { color: #5ee8c0; }
</style>
