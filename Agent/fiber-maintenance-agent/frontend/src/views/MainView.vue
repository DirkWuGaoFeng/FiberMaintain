<template>
  <div class="app-container">
    <svg class="bg-fib" viewBox="0 0 1440 900" preserveAspectRatio="none">
      <defs>
        <linearGradient id="gf" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#3fd0ff" stop-opacity="0"/>
          <stop offset=".5" stop-color="#3fd0ff"/>
          <stop offset="1" stop-color="#3fd0ff" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <path class="p1" d="M-60,140 C320,60 760,260 1500,120" stroke="url(#gf)"/>
      <path class="p2" d="M-60,470 C400,380 900,560 1500,430" stroke="url(#gf)"/>
      <path class="p3" d="M-60,760 C360,700 980,860 1500,720" stroke="url(#gf)"/>
    </svg>

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
          <h1>光纤维护服务系统</h1>
          <small>FIBER OPS · DEERFLOW 2.0 · FIBERHOME</small>
        </div>
      </div>
      <div class="top-status">
        <span class="pill"><i class="dot dot-g"></i>统计推送 WS :8766</span>
        <span class="pill"><i class="dot dot-g"></i>DeerFlow API :8000</span>
        <span class="pill"><i class="dot dot-c"></i>OLLAMA {{ llmModel }} 主</span>
        <span class="clock">{{ currentTime }}</span>
      </div>
    </header>

    <section class="stats-band">
      <div class="panel hud counters">
        <div class="sec">实时统计 <span class="r">FM-09 · 推送≤10s</span></div>
        <div class="cnt-row">
          <div class="cnt red">
            <label>🔴 红色连纤</label><b>{{ stats.red }}</b><small>紧急告警触发</small>
          </div>
          <div class="cnt yel">
            <label>🟡 黄色连纤</label><b>{{ stats.yellow }}</b><small>次要告警触发</small>
          </div>
          <div class="cnt tot">
            <label>有颜色总计</label><b>{{ stats.total }}</b><small>网元间连纤</small>
          </div>
        </div>
        <div class="almline">
          <span class="alm-chip u">紧急 <b>{{ stats.urgent }}</b></span>
          <span class="alm-chip m">次要 <b>{{ stats.minor }}</b></span>
          <span class="push-ts"><i>●</i> 推送 <span>{{ pushTime }}</span></span>
        </div>
      </div>

      <div class="panel hud trend-p">
        <div class="sec">红/黄连纤趋势 <span class="r">FM-10 · 5min粒度 · 保留7天</span></div>
        <div class="trend-head">
          <div class="ranges">
            <button v-for="r in ranges" :key="r.value"
              :class="{ on: currentRange === r.value }" @click="currentRange = r.value">
              {{ r.label }}
            </button>
          </div>
          <div class="legend">
            <span><i style="background:var(--red)"></i>红色</span>
            <span><i style="background:var(--amber)"></i>黄色</span>
          </div>
        </div>
        <div class="cv-wrap">
          <canvas ref="trendCanvas" @mousemove="handleTrendMouseMove" @mouseleave="handleTrendMouseLeave"></canvas>
          <div class="ctip" v-if="tooltip.visible" :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }">
            <span style="color:#8ba3c2">{{ tooltip.time }}</span><br>
            🔴 {{ tooltip.red }} · 🟡 {{ tooltip.yellow }}
          </div>
        </div>
      </div>

      <div class="panel pairs-p">
        <div class="sec">网元对分布</div>
        <div class="body">
          <div v-for="p in pairs" :key="p.a+p.b" class="pair">
            <span class="nm">{{ p.a }} ↔ {{ p.b }}</span>
            <span class="bar">
              <i class="sr" :style="{ width: (p.red/maxPairs*100)+'%' }"></i>
              <i class="sy" :style="{ width: (p.yellow/maxPairs*100)+'%' }"></i>
            </span>
            <span class="ct"><em>🔴{{ p.red }}</em> <u>🟡{{ p.yellow }}</u></span>
          </div>
        </div>
      </div>

      <div class="panel feed-p">
        <div class="sec">最近颜色变化 <span class="r">AL-05 订阅</span></div>
        <div class="body">
          <div v-for="(item, idx) in feedItems" :key="idx" class="fitem" :class="{ new: item.isNew }">
            <span class="tm">{{ item.time }}</span>
            <span class="fid">{{ item.fid }}</span>
            <span class="trans">
              <i class="d" :class="item.from"></i>→<i class="d" :class="item.to"></i>
              <span style="margin-left:4px">{{ colorText[item.to] }}</span>
            </span>
          </div>
        </div>
      </div>
    </section>

    <main>
      <aside class="rail">
        <button class="btn-new" @click="newSession">＋ 新建会话</button>
        <div class="panel sess">
          <div class="sec">会话管理</div>
          <div v-for="s in sessions" :key="s.id" class="sitem" :class="{ on: currentSession === s.id }"
            @click="currentSession = s.id">
            <b>{{ s.title }}</b><span>{{ s.time }}</span>
          </div>
        </div>
        <div class="panel">
          <div class="sec">Sub-Agent 注册表</div>
          <div class="agents">
            <div v-for="a in agents" :key="a.name" class="agrow" :class="{ busy: a.busy }">
              <i class="st"></i>
              <span class="nm">{{ a.name }}</span>
              <span class="mdl" :class="{ b: a.modelProfile === 'primary' }">{{ a.modelProfile === 'primary' ? '72B' : '14B' }}</span>
            </div>
          </div>
          <div class="conc">
            并发 <span>{{ concurrentCount }} / 5</span> · SubagentLimitMW
            <div class="cb"><i :style="{ width: (concurrentCount/5*100)+'%' }"></i></div>
          </div>
        </div>
        <div class="panel">
          <div class="sec">Markdown Skills</div>
          <div v-for="s in skills" :key="s.name" class="skill">
            <span class="fi">MD</span><span class="fn">{{ s.name }}</span><small>{{ s.tag }}</small>
          </div>
        </div>
      </aside>

      <section class="panel hud chat">
        <div class="chat-head">
          <span>🤖 Lead Agent</span><span class="tid">session: {{ currentSession }}</span>
          <div class="mw">
            <span>RAGInjectionMW</span><span>DomainValidationMW</span>
            <span>AuditLogMW</span><span>ModelDegradationMW</span>
          </div>
        </div>
        <div id="chatlog" ref="chatlog" class="chatlog">
          <div v-for="msg in messages" :key="msg.id" :class="msg.type">
            <div v-if="msg.type === 'ubub'" class="ubub">{{ msg.content }}</div>
            <div v-else-if="msg.type === 'amsg'" class="amsg">
              <div class="ava">DF</div>
              <div class="body">
                <div v-if="msg.thought" class="fold think">
                  <div class="fhead" @click="msg.thoughtOpen = !msg.thoughtOpen">
                    <span class="chev">▼</span>🤔 Lead Agent · 思考过程
                  </div>
                  <div class="fbody" v-show="msg.thoughtOpen">
                    <div v-for="(step, idx) in msg.thought" :key="idx" class="tstep">{{ step }}</div>
                  </div>
                </div>
                <div v-if="msg.tools" class="fold tool">
                  <div class="fhead" @click="msg.toolsOpen = !msg.toolsOpen">
                    <span class="chev">▼</span>🔧 工具调用 · {{ msg.tools.length }} 次
                  </div>
                  <div class="fbody" v-show="msg.toolsOpen">
                    <div v-for="(tool, idx) in msg.tools" :key="idx" class="trow">
                      <span class="ttag" :class="tool.tag">{{ tool.tag.toUpperCase() }}</span>
                      <span class="tname">{{ tool.name }}</span>
                      <span class="tnote">{{ tool.note }}</span>
                      <span class="tok">✅ {{ tool.ms }}ms</span>
                    </div>
                  </div>
                </div>
                <div v-if="msg.report" class="report">
                  <div v-for="(line, idx) in msg.report" :key="idx" class="rp-line" :class="line.c">
                    {{ line.t }}
                  </div>
                </div>
                <div v-if="msg.batch" class="batch">
                  <div class="bhead">📋 批量分析 · {{ msg.batch.length }} 条 · 并发 5
                    <span class="bprog"><i :style="{ width: msg.batchProgress + '%' }"></i></span>
                  </div>
                  <div class="brows">
                    <div v-for="(item, idx) in msg.batch" :key="idx" class="brow">
                      <span class="bid">{{ item.id }}</span>
                      <span class="brt">{{ item.rt }}</span>
                      <span class="bs" :class="{ ok: item.ok, fail: item.fail }">{{ item.status }}</span>
                    </div>
                  </div>
                </div>
                <div v-if="msg.done" class="done">{{ msg.done }}</div>
              </div>
            </div>
          </div>
        </div>
        <div class="quick">
          <button @click="quickAction('colored')">有颜色连纤</button>
          <button @click="quickAction('batch')">批量衰耗</button>
          <button @click="quickAction('stats')">统计</button>
          <button @click="quickAction('check')">网元巡检</button>
        </div>
        <div class="inrow">
          <input v-model="inputText" @keyup.enter="sendMessage"
            placeholder="输入自然语言指令，如：分析光纤 F019 的质量 / 分析所有紧急告警光纤…" autocomplete="off">
          <button class="send" :class="{ glow: sending }" @click="sendMessage">发送</button>
        </div>
      </section>

      <aside class="rail">
        <div class="panel topo-p">
          <div class="sec">拓扑示意
            <span class="r">TP-03 · 点击链路分析</span>
            <div class="topo-toggle">
              <button :class="{ on: topoMode === 'colored' }" @click="topoMode = 'colored'">有颜色</button>
              <button :class="{ on: topoMode === 'full' }" @click="topoMode = 'full'">全网</button>
            </div>
          </div>
          <div class="topo-wrap">
            <svg :viewBox="`0 0 660 ${topoHeight}`" class="topo">
              <defs>
                <filter id="glow">
                  <feGaussianBlur stdDeviation="2.2" result="b"/>
                  <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
                </filter>
              </defs>
              <path v-for="f in topologyFibers" :key="f.id" :id="'p'+f.id"
                class="fib" :class="f.color" :data-f="f.id" :d="f.path"
                :stroke-dasharray="f.isInter ? 'none' : '4,3'"
                @mousemove="showTopoTip($event, f)" @mouseleave="hideTopoTip" @click="analyzeFiber(f.id)">
              </path>
              <circle v-for="(anim, idx) in topologyAnims" :key="'anim'+idx"
                r="2.6" :fill="anim.color" filter="url(#glow)">
                <animateMotion :dur="anim.dur" repeatCount="indefinite">
                  <mpath :href="'#p'+anim.fid"/>
                </animateMotion>
              </circle>
              <g v-for="ne in topologyNEs" :key="ne.name">
                <rect class="ne-box" :x="ne.x" :y="ne.y" width="190" height="116" rx="5"/>
                <text class="ne-lb" :x="ne.x+12" :y="ne.y+22">{{ ne.name }}</text>
                <rect class="bchip a" :x="ne.x+12" :y="ne.y+32" width="52" height="16" rx="2"/>
                <text class="ne-st" :x="ne.x+17" :y="ne.y+43">有源×{{ ne.active }}</text>
                <rect class="bchip p" :x="ne.x+72" :y="ne.y+32" width="52" height="16" rx="2"/>
                <text class="ne-st" :x="ne.x+77" :y="ne.y+43">无源×{{ ne.passive }}</text>
                <text class="ne-st" :x="ne.x+12" :y="ne.y+60">{{ ne.activeBoards }}</text>
                <text class="ne-st" :x="ne.x+12" :y="ne.y+76">{{ ne.passiveBoards }}</text>
                <text class="ne-st" :x="ne.x+12" :y="ne.y+96" v-if="topoMode === 'full'" style="fill:#5a7a9a">— 网元内连纤虚线 —</text>
              </g>
            </svg>
            <div class="ttip" v-if="topoTip.visible" :style="{ left: topoTip.x + 'px', top: topoTip.y + 'px' }">
              {{ topoTip.text }}
            </div>
          </div>
        </div>
        <div class="panel fibers-p">
          <div class="sec">有颜色连纤 <span class="r">FM-08 · <span>{{ fiberCount }}</span> 条</span></div>
          <div class="fchips">
            <button v-for="f in fiberFilters" :key="f.value" :class="{ on: fiberFilter === f.value }"
              @click="fiberFilter = f.value">
              {{ f.label }}
            </button>
          </div>
          <div class="flist">
            <div v-for="f in filteredFibers" :key="f.id" class="frow" @click="analyzeFiber(f.id)">
              <i class="fdot" :class="f.color"></i>
              <span class="fid">{{ f.id }}</span>
              <span class="frt">{{ f.a }}→{{ f.b }} · 场景{{ f.scenario }}</span>
              <span class="fsl" :class="f.slClass">{{ f.span }}</span>
              <span class="fal" :class="f.alarmClass">{{ f.alarm }}</span>
            </div>
          </div>
        </div>
      </aside>
    </main>

    <footer>
      <span><b>需求规格说明书 v12.0</b>（DeerFlow 2.0 版）</span>
      <span>光纤维护系统</span>
      <span>操作对象：仅网元间连纤（src_ne_id ≠ dst_ne_id）</span>
      <span>Spanloss = OOP − IOP</span>
      <span style="margin-left:auto">统计粒度 5min · 保留 7 天 · 刷新 ≤10s</span>
    </footer>
    <div class="toast" :class="{ show: toastVisible }">{{ toastMsg }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useFiberStats } from '../composables/useFiberStats'
import { useTrendData } from '../composables/useTrendData'
import { getAllColoredFibers, getFiberScene, sendChatMessage, getStatus } from '../api'

const currentTime = ref('')
const pushTime = ref('--:--:--')
const llmModel = ref('qwen3.6')

const { stats: fiberStats, recentChanges, wsConnected } = useFiberStats()
const { points: trendPoints, fetchTrend } = useTrendData()

const stats = computed(() => ({
  red: fiberStats.value.red_count || 0,
  yellow: fiberStats.value.yellow_count || 0,
  total: fiberStats.value.total_colored || 0,
  urgent: fiberStats.value.red_count || 0,
  minor: fiberStats.value.yellow_count || 0,
}))

const feedItems = computed(() => {
  return recentChanges.value.slice(0, 6).map(c => ({
    time: new Date(c.timestamp).toLocaleTimeString(),
    fid: c.fiber_id,
    from: c.old_color === 'red' ? 'r' : c.old_color === 'yellow' ? 'y' : 'g',
    to: c.new_color === 'red' ? 'r' : c.new_color === 'yellow' ? 'y' : 'g',
    isNew: false,
  }))
})

const currentRange = ref('24h')
const ranges = [
  { label: '1h', value: '1h' },
  { label: '6h', value: '6h' },
  { label: '24h', value: '24h' },
  { label: '7d', value: '7d' },
]
const tooltip = ref({ visible: false, x: 0, y: 0, time: '', red: 0, yellow: 0 })
const trendData = ref({ red: [], yellow: [], times: [], anim: 1, hover: null })
const pairs = ref([])
const maxPairs = computed(() => pairs.value.length > 0 ? Math.max(...pairs.value.map(p => p.red + p.yellow)) : 1)
const colorText = { red: '红色', yellow: '黄色', green: '绿色' }

const currentSession = ref('')
const sessions = ref([])
const agents = ref([
  { name: 'topology-analyst', modelProfile: 'fast', busy: false },
  { name: 'data-collector', modelProfile: 'fast', busy: false },
  { name: 'analysis-expert', modelProfile: 'primary', busy: false },
  { name: 'report-generator', modelProfile: 'primary', busy: false },
  { name: 'rag-retriever', modelProfile: 'fast', busy: false },
])
const concurrentCount = ref(0)
const skills = ref([
  { name: 'fiber_spanloss_analysis.md', tag: '衰耗' },
  { name: 'fiber_color_diagnosis.md', tag: '颜色' },
  { name: 'batch_fiber_analysis.md', tag: '批量' },
  { name: 'fiber_trend_analysis.md', tag: '趋势' },
  { name: 'ne_health_check.md', tag: '巡检' },
])

const messages = ref([])
const inputText = ref('')
const sending = ref(false)
const chatlog = ref(null)
const trendCanvas = ref(null)

const topologyFibers = ref([])
const topologyAnims = ref([])
const topologyNEs = ref([])
const topologyBoards = ref([])
const topoTip = ref({ visible: false, x: 0, y: 0, text: '' })
const topoMode = ref('colored')
const cachedScenes = ref([])
const cachedColorLookup = ref({})
const topoHeight = computed(() => {
  const rows = Math.ceil(topologyNEs.value.length / 2)
  return Math.max(322, 28 + rows * 130 + 20)
})

const fiberFilter = ref('all')
const fiberFilters = [
  { label: '全部', value: 'all' },
  { label: '🔴', value: 'r' },
  { label: '🟡', value: 'y' },
]
const allFibers = ref([])
const fiberCount = computed(() => allFibers.value.length)
const filteredFibers = computed(() => {
  if (fiberFilter.value === 'all') return allFibers.value
  return allFibers.value.filter(f => f.color === fiberFilter.value)
})

async function fetchColoredFibers() {
  try {
    const { data } = await getAllColoredFibers()
    const colorMap = { GREEN: 'g', RED: 'r', YELLOW: 'y' }
    const fibers = (data.fibers || []).map(f => {
      const color = colorMap[f.color] || 'g'
      const alarmClass = color === 'r' ? 'u' : color === 'y' ? 'm' : ''
      return {
        id: 'F' + String(f.fiber.fiber_id).padStart(3, '0'),
        fiberId: f.fiber.fiber_id,
        a: 'NE-' + f.fiber.src_ne_id,
        b: 'NE-' + f.fiber.dst_ne_id,
        scenario: f.scenario_type || 1,
        span: '—',
        alarm: color === 'r' ? '紧急' : color === 'y' ? '次要' : '',
        color: color,
        slClass: '',
        alarmClass: alarmClass,
        src_ne_id: f.fiber.src_ne_id,
        dst_ne_id: f.fiber.dst_ne_id,
      }
    })
    allFibers.value = fibers

    const colorLookup = {}
    ;(data.fibers || []).forEach(f => {
      colorLookup[f.fiber.fiber_id] = colorMap[f.color] || 'g'
    })

    const scenes = await Promise.all(
      fibers.map(f => getFiberScene(f.fiberId).then(r => r.data).catch(() => null))
    )
    cachedScenes.value = scenes
    cachedColorLookup.value = colorLookup
    updateNEPairs(scenes, colorLookup)
    renderTopology()
  } catch (e) {
    console.error('Failed to fetch colored fibers:', e)
  }
}

function updateNEPairs(scenes, colorLookup) {
  const pairMap = {}
  scenes.forEach(s => {
    if (!s || !s.found || !s.scene) return
    const fiber = s.scene.inter_ne_fiber
    if (!fiber) return
    const a = 'NE-' + fiber.src_ne_id
    const b = 'NE-' + fiber.dst_ne_id
    const key = [a, b].sort().join('-')
    if (!pairMap[key]) {
      pairMap[key] = { a, b, red: 0, yellow: 0 }
    }
    const color = colorLookup[fiber.fiber_id] || 'g'
    if (color === 'r') pairMap[key].red++
    else if (color === 'y') pairMap[key].yellow++
  })
  pairs.value = Object.values(pairMap)
}

function renderTopology() {
  const scenes = cachedScenes.value
  const colorLookup = cachedColorLookup.value
  const isFull = topoMode.value === 'full'

  const neSet = new Set()
  const allFibers = []
  const neActiveBoards = {}
  const nePassiveBoards = {}

  scenes.forEach(s => {
    if (!s || !s.found || !s.scene) return
    const interFiber = s.scene.inter_ne_fiber
    if (interFiber) {
      neSet.add(interFiber.src_ne_id)
      neSet.add(interFiber.dst_ne_id)
      allFibers.push({
        fiberId: interFiber.fiber_id,
        src_ne_id: interFiber.src_ne_id,
        dst_ne_id: interFiber.dst_ne_id,
        src_board_id: interFiber.src_board_id,
        dst_board_id: interFiber.dst_board_id,
        isInter: true,
        color: colorLookup[interFiber.fiber_id] || 'g',
      })
    }
    // 全网模式：包含网元内连纤
    if (isFull) {
      ;(s.scene.ne_internal_fibers || []).forEach(f => {
        allFibers.push({
          fiberId: f.fiber_id,
          src_ne_id: f.src_ne_id,
          dst_ne_id: f.dst_ne_id,
          src_board_id: f.src_board_id,
          dst_board_id: f.dst_board_id,
          isInter: false,
          color: 'g',
        })
      })
    }
  })

  const neList = Array.from(neSet).sort((a, b) => a - b)
  const nePositions = {}
  const cols = 2
  const neBoxW = 190
  const neBoxH = 116
  const padX = 24
  const padY = 28
  const rowGap = 130
  neList.forEach((neId, idx) => {
    const col = idx % cols
    nePositions[neId] = {
      x: col === 0 ? padX : 660 - padX - neBoxW,
      y: padY + Math.floor(idx / cols) * rowGap
    }
    neActiveBoards[neId] = []
    nePassiveBoards[neId] = []
  })

  // 收集单盘信息
  scenes.forEach(s => {
    if (!s || !s.found || !s.scene) return
    if (s.scene.src_active_board && neActiveBoards[s.scene.src_active_board.ne_id]) {
      neActiveBoards[s.scene.src_active_board.ne_id].push(s.scene.src_active_board.board_id)
    }
    if (s.scene.dst_active_board && neActiveBoards[s.scene.dst_active_board.ne_id]) {
      neActiveBoards[s.scene.dst_active_board.ne_id].push(s.scene.dst_active_board.board_id)
    }
    ;(s.scene.passive_boards || []).forEach(b => {
      if (nePassiveBoards[b.ne_id]) nePassiveBoards[b.ne_id].push(b.board_id)
    })
  })

  const topoFibers = allFibers.map(f => {
    const srcPos = nePositions[f.src_ne_id] || { x: padX, y: padY }
    const dstPos = nePositions[f.dst_ne_id] || { x: 660 - padX - neBoxW, y: padY }
    const midX = (srcPos.x + dstPos.x) / 2
    const midY = (srcPos.y + dstPos.y) / 2
    return {
      id: 'F' + String(f.fiberId).padStart(3, '0'),
      color: f.color,
      ne: 'NE-' + f.src_ne_id + '→NE-' + f.dst_ne_id,
      isInter: f.isInter,
      boards: 'BD-' + f.src_board_id + ' ↔ BD-' + f.dst_board_id,
      path: `M${srcPos.x + neBoxW/2},${srcPos.y + neBoxH/2} C${midX},${midY} ${midX},${midY} ${dstPos.x + neBoxW/2},${dstPos.y + neBoxH/2}`
    }
  })
  topologyFibers.value = topoFibers
  topologyAnims.value = topoFibers.filter(f => f.color !== 'g').map((f, i) => ({
    fid: f.id,
    color: f.color === 'r' ? '#ff8a8d' : '#ffd27f',
    dur: (2 + i * 0.4) + 's'
  }))
  topologyNEs.value = neList.map(neId => {
    const pos = nePositions[neId]
    const activeIds = [...new Set(neActiveBoards[neId] || [])]
    const passiveIds = [...new Set(nePassiveBoards[neId] || [])]
    return {
      name: 'NE-' + neId,
      site: '',
      x: pos.x,
      y: pos.y,
      active: activeIds.length,
      passive: passiveIds.length,
      activeBoards: activeIds.map(id => 'BD-' + id).join(' '),
      passiveBoards: passiveIds.map(id => 'BD-' + id).join(' '),
    }
  })
}

watch(topoMode, () => renderTopology())

const toastVisible = ref(false)
const toastMsg = ref('')

function showToast(msg) {
  toastMsg.value = msg
  toastVisible.value = true
  setTimeout(() => toastVisible.value = false, 2200)
}

function newSession() {
  const newId = 's-' + Date.now().toString().slice(-12)
  sessions.value.unshift({
    id: newId,
    title: '新会话',
    time: '刚刚 · 进行中',
  })
  currentSession.value = newId
  messages.value = []
  showToast('新建会话成功')
}

function quickAction(type) {
  const actions = {
    colored: '查询所有有颜色连纤',
    batch: '批量分析所有红色连纤的衰耗',
    stats: '查询当前连纤统计信息',
    check: '执行网元巡检',
  }
  inputText.value = actions[type] || ''
  inputText.value && showToast('已填入指令：' + inputText.value)
}

function analyzeFiber(fid) {
  inputText.value = '分析光纤 ' + fid + ' 的质量'
  showToast('已填入指令 → ' + fid)
}

function showTopoTip(event, fiber) {
  const rect = event.currentTarget.closest('.topo-wrap').getBoundingClientRect()
  const colorIcon = fiber.color === 'r' ? '🔴' : fiber.color === 'y' ? '🟡' : '🟢'
  const typeLabel = fiber.isInter ? '网元间' : '网元内'
  const info = `${fiber.id} · ${fiber.ne} · ${colorIcon} ${typeLabel}\n${fiber.boards}`
  topoTip.value = {
    visible: true,
    x: Math.min(event.clientX - rect.left + 12, rect.width - 180),
    y: Math.max(event.clientY - rect.top - 40, 2),
    text: info,
  }
}

function hideTopoTip() {
  topoTip.value.visible = false
}

async function sendMessage() {
  if (!inputText.value.trim() || sending.value) return
  sending.value = true

  const userMsg = {
    id: Date.now(),
    type: 'ubub',
    content: inputText.value,
  }
  messages.value.push(userMsg)
  inputText.value = ''
  scrollToBottom()

  const aiMsg = {
    id: Date.now() + 1,
    type: 'amsg',
    thoughtOpen: true,
    toolsOpen: false,
    thought: [],
    tools: [],
    report: [],
    done: '',
  }
  messages.value.push(aiMsg)
  scrollToBottom()

  try {
    await sendChatMessage(userMsg.content, (event) => {
      if (event.type === 'thought') {
        aiMsg.thought.push(event.content)
      } else if (event.type === 'tool') {
        aiMsg.tools.push({
          tag: event.tag,
          name: event.name,
          note: event.note,
          ms: event.ms,
        })
      } else if (event.type === 'report') {
        aiMsg.report.push({ c: event.type, t: event.content })
      } else if (event.type === 'done') {
        aiMsg.done = event.content
      } else if (event.type === 'message') {
        aiMsg.report.push({ c: 'p', t: event.content })
      }
      scrollToBottom()
    })
    if (!aiMsg.done) {
      aiMsg.done = '✅ 完成'
    }
  } catch (e) {
    aiMsg.report.push({ c: 'p', t: '❌ 服务暂时不可用，请稍后重试' })
    aiMsg.done = '❌ 失败'
    console.error('Chat error:', e)
  }
  
  sending.value = false
}

function scrollToBottom() {
  setTimeout(() => {
    if (chatlog.value) {
      chatlog.value.scrollTop = chatlog.value.scrollHeight
    }
  }, 50)
}

function updateTime() {
  const now = new Date()
  const pad = n => String(n).padStart(2, '0')
  currentTime.value = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate()) + ' ' +
    pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds())
  pushTime.value = pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds())
}

function genTrend(range) {
  const N = { '1h': 13, '6h': 73, '24h': 289, '7d': 2017 }[range]
  const stride = Math.max(1, Math.ceil(N / 340))
  const n = Math.floor((N - 1) / stride) + 1
  const now = Date.now()
  let wr = 9 + Math.random() * 4, wy = 25 + Math.random() * 4
  const R = [], Y = [], T = []
  for (let i = 0; i < n; i++) {
    const t = new Date(now - (n - 1 - i) * 5 * 60000 * stride)
    const wave = Math.sin((t.getHours() + t.getMinutes() / 60 - 3) / 24 * Math.PI * 2)
    wr += (Math.random() - 0.5) * 1.6
    wy += (Math.random() - 0.5) * 2
    R.push(Math.max(3, Math.min(19, wr + wave * 3.4)))
    Y.push(Math.max(14, Math.min(38, wy + wave * 4.6)))
    T.push(t)
  }
  trendData.value = { red: R, yellow: Y, times: T, anim: 1, hover: null }
}

function drawTrend() {
  const canvas = trendCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const w = canvas.clientWidth
  const h = canvas.clientHeight
  const dpr = window.devicePixelRatio || 1
  if (canvas.width !== w * dpr) {
    canvas.width = w * dpr
    canvas.height = h * dpr
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)
  const L = 30, R = 8, T = 8, B = 20
  const n = trendData.value.red.length
  const max = Math.ceil(Math.max(...trendData.value.red, ...trendData.value.yellow) * 1.15 / 5) * 5
  const X = i => L + (w - L - R) * i / (n - 1)
  const Y = v => T + (h - T - B) * (1 - v * trendData.value.anim / max)
  ctx.font = '9.5px JetBrains Mono'
  ctx.fillStyle = '#5b7391'
  ctx.strokeStyle = 'rgba(79,141,255,.12)'
  for (let g = 0; g <= 3; g++) {
    const v = max * g / 3
    const y = Y(v)
    ctx.beginPath()
    ctx.moveTo(L, y)
    ctx.lineTo(w - R, y)
    ctx.stroke()
    ctx.fillText(Math.round(v), 4, y + 3)
  }
  const step = Math.max(1, Math.floor(n / 5))
  for (let i = 0; i < n; i += step) {
    const lb = trendData.value.times[i]
    if (!lb || !(lb instanceof Date) || isNaN(lb.getTime())) continue
    const label = currentRange.value === '7d'
      ? (lb.getMonth() + 1) + '/' + lb.getDate()
      : String(lb.getHours()).padStart(2, '0') + ':' + String(lb.getMinutes()).padStart(2, '0')
    ctx.fillText(label, X(i) - 10, h - 6)
  }
  const line = (arr, col, fill) => {
    ctx.beginPath()
    arr.forEach((v, i) => {
      const x = X(i), y = Y(v)
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)
    })
    ctx.strokeStyle = col
    ctx.lineWidth = 1.8
    ctx.stroke()
    ctx.lineTo(X(n - 1), h - B)
    ctx.lineTo(L, h - B)
    ctx.closePath()
    const g = ctx.createLinearGradient(0, T, 0, h - B)
    g.addColorStop(0, fill)
    g.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = g
    ctx.fill()
  }
  line(trendData.value.yellow, '#ffb224', 'rgba(255,178,36,.20)')
  line(trendData.value.red, '#ff5257', 'rgba(255,82,87,.24)')
  if (trendData.value.hover != null) {
    const i = trendData.value.hover
    const x = X(i)
    ctx.strokeStyle = 'rgba(220,232,247,.35)'
    ctx.setLineDash([3, 3])
    ctx.beginPath()
    ctx.moveTo(x, T)
    ctx.lineTo(x, h - B)
    ctx.stroke()
    ctx.setLineDash([])
    [[trendData.value.red[i], '#ff5257'], [trendData.value.yellow[i], '#ffb224']].forEach(([v, c]) => {
      ctx.beginPath()
      ctx.arc(x, Y(v), 3.4, 0, 7)
      ctx.fillStyle = c
      ctx.fill()
      ctx.strokeStyle = '#0a1424'
      ctx.lineWidth = 1.6
      ctx.stroke()
    })
  }
}

function animTrend() {
  trendData.value.anim = 0
  const t0 = performance.now()
  const animate = t => {
    trendData.value.anim = Math.min(1, (t - t0) / 520)
    trendData.value.anim = 1 - Math.pow(1 - trendData.value.anim, 3)
    drawTrend()
    if (trendData.value.anim < 1) requestAnimationFrame(animate)
  }
  requestAnimationFrame(animate)
}

function handleTrendMouseMove(event) {
  const canvas = trendCanvas.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const n = trendData.value.red.length
  if (n === 0) return
  const i = Math.round((event.clientX - rect.left - 30) / (rect.width - 38) * (n - 1))
  if (isNaN(i) || i < 0 || i >= n) {
    trendData.value.hover = null
    tooltip.value.visible = false
    drawTrend()
    return
  }
  trendData.value.hover = i
  drawTrend()
  const t = trendData.value.times[i]
  if (!t || !(t instanceof Date) || isNaN(t.getTime())) {
    tooltip.value.visible = false
    return
  }
  const lb = currentRange.value === '7d'
    ? (t.getMonth() + 1) + '/' + t.getDate() + ' ' + String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0')
    : String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0')
  tooltip.value = {
    visible: true,
    x: Math.min(event.clientX - rect.left + 14, rect.width - 110),
    y: Math.max(event.clientY - rect.top - 44, 4),
    time: lb,
    red: Math.round(trendData.value.red[i]),
    yellow: Math.round(trendData.value.yellow[i]),
  }
}

function handleTrendMouseLeave() {
  trendData.value.hover = null
  tooltip.value.visible = false
  drawTrend()
}

watch(currentRange, async (newRange) => {
  const hours = { '1h': 1, '6h': 6, '24h': 24, '7d': 168 }[newRange]
  await fetchTrend(hours)
  if (trendPoints.value.length > 0) {
    trendData.value.red = trendPoints.value.map(p => p.red_count)
    trendData.value.yellow = trendPoints.value.map(p => p.yellow_count)
    trendData.value.times = trendPoints.value.map(p => new Date(String(p.timestamp).replace(' ', 'T')))
  } else {
    genTrend(newRange)
  }
  trendData.value.hover = null
  tooltip.value.visible = false
  nextTick(() => {
    drawTrend()
    animTrend()
  })
})

let timeInterval = null

onMounted(async () => {
  updateTime()
  timeInterval = setInterval(updateTime, 1000)
  fetchColoredFibers()
  try {
    const { data } = await getStatus()
    if (data.llm && data.llm.model) {
      llmModel.value = data.llm.model
    }
  } catch (e) {
    console.error('Failed to get status:', e)
  }
  await fetchTrend(24)
  if (trendPoints.value.length > 0) {
    trendData.value.red = trendPoints.value.map(p => p.red_count)
    trendData.value.yellow = trendPoints.value.map(p => p.yellow_count)
    trendData.value.times = trendPoints.value.map(p => new Date(String(p.timestamp).replace(' ', 'T')))
  } else {
    genTrend(currentRange.value)
  }
  nextTick(() => {
    drawTrend()
    animTrend()
  })
})

onUnmounted(() => {
  if (timeInterval) clearInterval(timeInterval)
})
</script>

<style scoped>
.app-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

header {
  height: 54px;
  flex: none;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 16px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, #0d1a2e, #0a1424);
  position: relative;
  z-index: 1;
}

.brand {
  display: flex;
  align-items: center;
  gap: 11px;
}

.brand svg {
  width: 30px;
  height: 30px;
}

.brand h1 {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: .04em;
}

.brand small {
  display: block;
  font-family: var(--disp);
  font-size: 10px;
  letter-spacing: .28em;
  color: var(--tx3);
  font-weight: 600;
}

.top-status {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.clock {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--cyan);
  letter-spacing: .06em;
  margin-left: 6px;
}

.stats-band {
  flex: none;
  display: grid;
  gap: 12px;
  padding: 12px 16px 4px;
  grid-template-columns: 308px minmax(0, 1fr) 262px 292px;
  position: relative;
  z-index: 1;
}

.counters {
  display: flex;
  flex-direction: column;
  padding-bottom: 8px;
}

.cnt-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
  padding: 0 10px;
}

.cnt {
  border-radius: 6px;
  padding: 8px 10px 7px;
  border: 1px solid var(--line);
  transition: transform .2s;
}

.cnt:hover { transform: translateY(-2px); }

.cnt.red {
  background: linear-gradient(180deg, rgba(255, 82, 87, .16), rgba(255, 82, 87, .04));
  border-color: rgba(255, 82, 87, .4);
}

.cnt.yel {
  background: linear-gradient(180deg, rgba(255, 178, 36, .14), rgba(255, 178, 36, .04));
  border-color: rgba(255, 178, 36, .4);
}

.cnt.tot {
  background: linear-gradient(180deg, rgba(63, 208, 255, .12), rgba(63, 208, 255, .03));
  border-color: rgba(63, 208, 255, .35);
}

.cnt label {
  font-size: 10px;
  color: var(--tx2);
  letter-spacing: .1em;
}

.cnt b {
  display: block;
  font-family: var(--disp);
  font-weight: 700;
  font-size: 34px;
  line-height: 1.05;
  margin-top: 2px;
}

.cnt.red b { color: var(--red); text-shadow: 0 0 18px rgba(255, 82, 87, .5); }
.cnt.yel b { color: var(--amber); text-shadow: 0 0 18px rgba(255, 178, 36, .45); }
.cnt.tot b { color: var(--cyan); }

.cnt small { font-size: 10px; font-family: var(--mono); color: var(--tx3); }

.almline { display: flex; gap: 6px; padding: 8px 10px 0; align-items: center; }

.alm-chip {
  font-size: 10.5px;
  font-family: var(--mono);
  padding: 2px 8px;
  border-radius: 3px;
  border: 1px solid var(--line);
}

.alm-chip.u { color: var(--red); border-color: rgba(255, 82, 87, .4); background: rgba(255, 82, 87, .08); }
.alm-chip.m { color: var(--amber); border-color: rgba(255, 178, 36, .4); background: rgba(255, 178, 36, .07); }

.push-ts { margin-left: auto; font-size: 10px; color: var(--tx3); font-family: var(--mono); }
.push-ts i { color: var(--green); font-style: normal; }

.trend-p { display: flex; flex-direction: column; min-width: 0; }

.trend-head { display: flex; align-items: center; gap: 10px; padding: 0 12px; }

.ranges { display: flex; border: 1px solid var(--line); border-radius: 4px; overflow: hidden; }

.ranges button {
  background: transparent;
  border: none;
  color: var(--tx2);
  font-family: var(--mono);
  font-size: 11px;
  padding: 3px 10px;
  cursor: pointer;
  transition: .18s;
}

.ranges button:hover { color: var(--cyan); }
.ranges button.on { background: rgba(63, 208, 255, .16); color: var(--cyan); }

.legend { display: flex; gap: 12px; margin-left: auto; font-size: 11px; color: var(--tx2); }

.legend i { width: 14px; height: 3px; border-radius: 2px; display: inline-block; margin-right: 5px; vertical-align: middle; }

.cv-wrap { flex: 1; position: relative; min-height: 118px; margin: 2px 6px 6px; }

canvas { position: absolute; inset: 0; width: 100%; height: 100%; }

.ctip {
  position: absolute;
  display: block;
  pointer-events: none;
  z-index: 5;
  background: #0a1626;
  border: 1px solid var(--line2);
  border-radius: 5px;
  padding: 6px 9px;
  font-family: var(--mono);
  font-size: 11px;
  box-shadow: 0 6px 16px rgba(0, 0, 0, .5);
  white-space: nowrap;
}

.pairs-p .body { padding: 2px 12px 10px; display: flex; flex-direction: column; gap: 8px; max-height: 140px; overflow-y: auto; }

.pair { display: grid; grid-template-columns: 86px 1fr 56px; align-items: center; gap: 8px; font-size: 11px; }

.pair .nm { font-family: var(--mono); color: var(--tx2); white-space: nowrap; }

.pair .bar { height: 9px; background: #0a1524; border-radius: 3px; overflow: hidden; display: flex; border: 1px solid #16283f; }

.pair .bar i { height: 100%; transition: width .8s cubic-bezier(.2, .7, .3, 1); }

.pair .bar .sr { background: linear-gradient(90deg, #c2373c, var(--red)); }
.pair .bar .sy { background: linear-gradient(90deg, #c07f10, var(--amber)); }

.pair .ct { font-family: var(--mono); font-size: 10.5px; text-align: right; white-space: nowrap; }

.pair .ct em { font-style: normal; color: var(--red); }
.pair .ct u { text-decoration: none; color: var(--amber); }

.feed-p .body { padding: 0 8px 8px; max-height: 132px; overflow: hidden; }

.fitem {
  display: grid;
  grid-template-columns: 56px 42px 1fr;
  gap: 6px;
  align-items: center;
  font-size: 11px;
  padding: 4px 6px;
  border-radius: 4px;
}

.fitem.new { animation: slidein .5s cubic-bezier(.2, .7, .3, 1), hl 2.4s; }

.fitem .tm { font-family: var(--mono); color: var(--tx3); font-size: 10.5px; }

.fitem .fid { font-family: var(--mono); color: var(--tx); }

.trans { display: flex; align-items: center; gap: 4px; font-size: 10px; color: var(--tx3); }

.trans .d { width: 8px; height: 8px; border-radius: 50%; }

.d.r { background: var(--red); box-shadow: 0 0 5px var(--red); }
.d.y { background: var(--amber); box-shadow: 0 0 5px var(--amber); }
.d.g { background: var(--green); }

main {
  flex: 1;
  min-height: 0;
  display: grid;
  gap: 12px;
  padding: 12px 16px;
  grid-template-columns: 246px minmax(0, 1fr) 348px;
  position: relative;
  z-index: 1;
}

.rail { display: flex; flex-direction: column; gap: 12px; min-height: 0; overflow-y: auto; }

.btn-new {
  flex: none;
  padding: 9px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
  border: 1px solid rgba(63, 208, 255, .5);
  color: var(--cyan);
  letter-spacing: .1em;
  background: linear-gradient(180deg, rgba(63, 208, 255, .16), rgba(63, 208, 255, .05));
  transition: .2s;
}

.btn-new:hover { box-shadow: 0 0 16px rgba(63, 208, 255, .35); transform: translateY(-1px); }

.sess { padding-bottom: 6px; }

.sitem { padding: 7px 12px; cursor: pointer; border-left: 2px solid transparent; transition: .15s; }

.sitem:hover { background: rgba(63, 208, 255, .06); }
.sitem.on { border-left-color: var(--cyan); background: rgba(63, 208, 255, .09); }

.sitem b { display: block; font-size: 12.5px; font-weight: 500; }
.sitem span { font-size: 10.5px; color: var(--tx3); font-family: var(--mono); }

.agrow {
  display: grid;
  grid-template-columns: 8px 1fr auto;
  gap: 8px;
  align-items: center;
  padding: 5px 12px;
  font-size: 11.5px;
  transition: background .3s;
}

.agrow .nm { font-family: var(--mono); color: var(--tx2); }

.agrow .mdl {
  font-family: var(--mono);
  font-size: 9.5px;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid var(--line);
  color: var(--tx3);
}

.agrow .mdl.b { color: var(--cyan); border-color: rgba(63, 208, 255, .4); }

.agrow.busy { background: rgba(63, 208, 255, .09); }

.agrow.busy .st { background: var(--cyan); box-shadow: 0 0 7px var(--cyan); animation: pulse 1s infinite; }

.agrow .st { width: 7px; height: 7px; border-radius: 50%; background: #3d5a7d; transition: .3s; }

.conc { margin: 6px 12px 10px; font-size: 10.5px; color: var(--tx3); font-family: var(--mono); }

.conc .cb { height: 5px; background: #0a1524; border: 1px solid #16283f; border-radius: 3px; margin-top: 4px; overflow: hidden; }

.conc .cb i { display: block; height: 100%; background: linear-gradient(90deg, var(--blue), var(--cyan)); transition: width .6s; }

.skill { display: flex; gap: 8px; align-items: center; padding: 5px 12px; font-size: 11px; transition: .15s; }

.skill:hover { background: rgba(63, 208, 255, .06); transform: translateX(2px); }

.skill .fi { color: var(--blue); font-family: var(--mono); font-size: 10px; border: 1px solid var(--line); border-radius: 3px; padding: 1px 4px; }

.skill .fn { font-family: var(--mono); color: var(--tx2); }
.skill small { margin-left: auto; color: var(--tx3); font-size: 10px; }

.chat { display: flex; flex-direction: column; min-height: 0; }

.chat-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  border-bottom: 1px solid var(--line);
  font-size: 12px;
  color: var(--tx2);
}

.chat-head .tid { font-family: var(--mono); color: var(--tx3); font-size: 10.5px; }

.chat-head .mw { margin-left: auto; display: flex; gap: 5px; flex-wrap: wrap; }

.chat-head .mw span {
  font-size: 9.5px;
  font-family: var(--mono);
  color: var(--tx3);
  border: 1px solid var(--line);
  padding: 1px 6px;
  border-radius: 3px;
}

.chatlog {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  scroll-behavior: smooth;
}

.dayline { text-align: center; font-size: 10.5px; color: var(--tx3); font-family: var(--mono); letter-spacing: .14em; }

.ubub {
  align-self: flex-end;
  max-width: 76%;
  padding: 9px 13px;
  border-radius: 8px 8px 2px 8px;
  background: linear-gradient(180deg, rgba(63, 208, 255, .2), rgba(63, 208, 255, .08));
  border: 1px solid rgba(63, 208, 255, .4);
  font-size: 13px;
  animation: rise .35s both;
}

.amsg { display: flex; gap: 10px; animation: rise .4s both; }

.ava {
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  background: linear-gradient(145deg, #123152, #0c1e36);
  border: 1px solid var(--line2);
  font-family: var(--disp);
  font-weight: 700;
  font-size: 11px;
  color: var(--cyan);
}

.amsg .body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; }

.fold { border: 1px solid var(--line); border-radius: 6px; background: rgba(9, 17, 30, .6); overflow: hidden; }

.fold > .fhead {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 11px;
  cursor: pointer;
  user-select: none;
  font-size: 11.5px;
  color: var(--tx2);
  transition: background .15s;
}

.fold > .fhead:hover { background: rgba(63, 208, 255, .06); }

.fold .chev { transition: transform .25s; color: var(--tx3); font-size: 10px; }
.fold.closed .chev { transform: rotate(-90deg); }
.fold.closed .fbody { display: none; }

.fold.think { border-left: 2px solid var(--cyan); }
.fold.tool { border-left: 2px solid var(--blue); }

.fbody { padding: 4px 11px 9px 26px; }

.tstep { font-size: 12px; color: var(--tx2); padding: 3px 0; position: relative; animation: rise .3s both; }

.tstep::before { content: '├─'; position: absolute; left: -16px; color: #33507a; font-family: var(--mono); font-size: 10px; }
.tstep:last-child::before { content: '└─'; }

.tstep code { font-family: var(--mono); font-size: 11px; color: var(--cyan); background: rgba(63, 208, 255, .1); padding: 0 5px; border-radius: 3px; }

.trow { display: flex; align-items: center; gap: 8px; padding: 3.5px 0; font-size: 11.5px; animation: rise .3s both; }

.ttag { font-family: var(--mono); font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 3px; letter-spacing: .06em; flex: none; }

.ttag.mcp { color: var(--cyan); background: rgba(63, 208, 255, .13); border: 1px solid rgba(63, 208, 255, .35); }
.ttag.sb { color: var(--amber); background: rgba(255, 178, 36, .12); border: 1px solid rgba(255, 178, 36, .35); }
.ttag.rag { color: var(--green); background: rgba(47, 214, 163, .12); border: 1px solid rgba(47, 214, 163, .35); }

.tname { font-family: var(--mono); color: var(--tx2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tok { margin-left: auto; font-family: var(--mono); font-size: 10.5px; color: var(--green); flex: none; }
.tnote { font-size: 10.5px; color: var(--tx3); }

.report {
  border: 1px solid #234067;
  border-radius: 6px;
  padding: 13px 15px;
  background: linear-gradient(180deg, #0e1e36, #0b1728);
  box-shadow: inset 0 1px 0 rgba(120, 180, 255, .08);
}

.rp-line { font-size: 12.8px; line-height: 1.75; color: #c9d9ef; word-break: break-all; }

.rp-line.h2 { font-size: 15px; font-weight: 700; color: #fff; padding-left: 9px; border-left: 3px solid var(--cyan); margin: 2px 0 6px; }
.rp-line.h3 { font-size: 13px; font-weight: 700; color: var(--cyan); margin-top: 6px; }
.rp-line.li { padding-left: 16px; position: relative; }
.rp-line.li::before { content: '▸'; position: absolute; left: 2px; color: var(--cyan); }
.rp-line.hr { border-top: 1px dashed #27405f; margin: 8px 0 4px; height: 0; }
.rp-line.meta { font-family: var(--mono); font-size: 10.5px; color: var(--tx3); }
.rp-line b { color: #fff; }
.rp-line code { font-family: var(--mono); font-size: 11px; color: var(--cyan); background: rgba(63, 208, 255, .1); padding: 0 5px; border-radius: 3px; }

.done { font-size: 11px; color: var(--green); font-family: var(--mono); animation: rise .4s both; }

.batch { border: 1px solid var(--line); border-radius: 6px; background: rgba(9, 17, 30, .6); padding: 10px 12px; }

.bhead { display: flex; align-items: center; gap: 10px; font-size: 11.5px; color: var(--tx2); margin-bottom: 8px; }

.bprog { flex: 1; height: 5px; background: #0a1524; border: 1px solid #16283f; border-radius: 3px; overflow: hidden; }
.bprog i { display: block; height: 100%; background: linear-gradient(90deg, var(--blue), var(--cyan)); transition: width .5s; }

.brow { display: grid; grid-template-columns: 48px 1fr auto; gap: 8px; align-items: center; font-size: 11.5px; padding: 3px 0; animation: rise .3s both; }

.brow .bid { font-family: var(--mono); color: var(--tx); }
.brow .brt { color: var(--tx3); font-size: 10.5px; font-family: var(--mono); }
.brow .bs { font-family: var(--mono); font-size: 10.5px; color: var(--tx3); }
.brow .bs.ok { color: var(--green); }
.brow .bs.fail { color: var(--red); }

.quick { flex: none; display: flex; gap: 8px; padding: 10px 14px 0; flex-wrap: wrap; }

.quick button {
  background: rgba(79, 141, 255, .08);
  border: 1px solid var(--line);
  color: var(--tx2);
  font-size: 11.5px;
  padding: 4px 12px;
  border-radius: 20px;
  cursor: pointer;
  transition: .18s;
}

.quick button:hover:not(:disabled) {
  border-color: var(--cyan);
  color: var(--cyan);
  transform: translateY(-1px);
  box-shadow: 0 3px 10px rgba(63, 208, 255, .18);
}

.inrow { flex: none; display: flex; gap: 10px; padding: 10px 14px 14px; }

.inrow input {
  flex: 1;
  background: #0a1524;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--tx);
  padding: 10px 13px;
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: .2s;
}

.inrow input:focus { border-color: var(--cyan); box-shadow: 0 0 0 3px rgba(63, 208, 255, .12); }

.inrow .send {
  padding: 0 22px;
  border-radius: 6px;
  border: 1px solid rgba(63, 208, 255, .55);
  cursor: pointer;
  background: linear-gradient(180deg, rgba(63, 208, 255, .25), rgba(63, 208, 255, .08));
  color: var(--cyan);
  font-weight: 700;
  font-size: 13px;
  letter-spacing: .14em;
  transition: .2s;
}

.inrow .send:hover { box-shadow: 0 0 18px rgba(63, 208, 255, .4); }
.inrow .send.glow { animation: sendg 1s infinite; }

.topo-p { flex: none; }

.topo-wrap { position: relative; padding: 2px 6px 8px; }
.topo-toggle { display: inline-flex; gap: 0; margin-left: 8px; }
.topo-toggle button {
  background: transparent; border: 1px solid var(--line2); color: var(--fg2);
  font-size: 10px; padding: 2px 8px; cursor: pointer; font-family: var(--mono);
  transition: all .15s;
}
.topo-toggle button:first-child { border-radius: 3px 0 0 3px; }
.topo-toggle button:last-child { border-radius: 0 3px 3px 0; border-left: none; }
.topo-toggle button.on { background: var(--accent); color: #0a1626; border-color: var(--accent); }

.topo-wrap svg { width: 100%; height: auto; display: block; }

.ne-box { fill: rgba(14, 30, 52, .85); stroke: #2a4568; stroke-width: 1; }
.ne-lb { font-family: var(--disp); font-weight: 700; font-size: 12px; fill: #cfe2f8; letter-spacing: .06em; }
.ne-st { font-size: 7.5px; fill: #5b7391; font-family: var(--mono); }

.bchip { stroke-width: .8; }
.bchip.a { fill: rgba(63, 208, 255, .14); stroke: rgba(63, 208, 255, .5); }
.bchip.p { fill: rgba(79, 141, 255, .1); stroke: #3a5b8c; }

.fib { fill: none; stroke-width: 2; cursor: pointer; transition: stroke-width .15s; }
.fib:hover { stroke-width: 3.6; }
.fib.r { stroke: var(--red); stroke-dasharray: 7 5; animation: dashm 1s linear infinite; filter: drop-shadow(0 0 4px rgba(255, 82, 87, .8)); }
.fib.y { stroke: var(--amber); filter: drop-shadow(0 0 3px rgba(255, 178, 36, .55)); }
.fib.g { stroke: var(--green); opacity: .75; }

.ttip {
  position: absolute;
  display: block;
  pointer-events: none;
  z-index: 6;
  background: #0a1626;
  border: 1px solid var(--line2);
  border-radius: 5px;
  padding: 5px 9px;
  font-family: var(--mono);
  font-size: 10.5px;
  box-shadow: 0 6px 16px rgba(0, 0, 0, .5);
  white-space: pre;
}

.fibers-p { flex: 1; min-height: 0; display: flex; flex-direction: column; }

.fchips { display: flex; gap: 6px; padding: 0 12px 8px; }

.fchips button {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--tx2);
  font-size: 11px;
  padding: 2px 10px;
  border-radius: 3px;
  cursor: pointer;
  transition: .15s;
  font-family: var(--mono);
}

.fchips button.on { border-color: var(--cyan); color: var(--cyan); background: rgba(63, 208, 255, .1); }

.flist { flex: 1; min-height: 200px; max-height: 400px; overflow-y: auto; padding: 0 8px 8px; scrollbar-width: thin; scrollbar-color: rgba(63, 208, 255, .3) rgba(0, 0, 0, .2); }

.frow {
  display: grid;
  grid-template-columns: 12px 46px 1fr 54px 40px;
  gap: 7px;
  align-items: center;
  padding: 6px 8px;
  border-radius: 5px;
  cursor: pointer;
  border-left: 2px solid transparent;
  transition: .15s;
  font-size: 11.5px;
}

.frow:hover { background: rgba(63, 208, 255, .07); border-left-color: var(--cyan); transform: translateX(2px); }

.fdot { width: 8px; height: 8px; border-radius: 50%; }
.fdot.r { background: var(--red); box-shadow: 0 0 6px var(--red); animation: pulse 1.4s infinite; }
.fdot.y { background: var(--amber); box-shadow: 0 0 5px var(--amber); }

.frow .fid { font-family: var(--mono); color: var(--tx); }
.frow .frt { font-family: var(--mono); font-size: 10.5px; color: var(--tx3); }
.frow .fsl { font-family: var(--mono); font-size: 10.5px; text-align: right; }

.fsl.bad { color: var(--red); }
.fsl.mid { color: var(--amber); }

.fal { font-size: 9.5px; text-align: center; border-radius: 3px; padding: 1px 0; font-family: var(--mono); }
.fal.u { color: var(--red); background: rgba(255, 82, 87, .12); border: 1px solid rgba(255, 82, 87, .35); }
.fal.m { color: var(--amber); background: rgba(255, 178, 36, .1); border: 1px solid rgba(255, 178, 36, .35); }

footer {
  flex: none;
  padding: 7px 16px;
  border-top: 1px solid var(--line);
  font-size: 10.5px;
  color: var(--tx3);
  font-family: var(--mono);
  display: flex;
  gap: 18px;
  background: #0a1424;
  flex-wrap: wrap;
  position: relative;
  z-index: 1;
}

footer b { color: var(--tx2); font-weight: 500; }

.toast {
  position: fixed;
  left: 50%;
  bottom: 44px;
  transform: translateX(-50%) translateY(20px);
  z-index: 99;
  background: #0d1e34;
  border: 1px solid var(--line2);
  color: var(--tx);
  padding: 8px 18px;
  border-radius: 6px;
  font-size: 12px;
  opacity: 0;
  pointer-events: none;
  transition: .3s;
  box-shadow: 0 8px 24px rgba(0, 0, 0, .5);
}

.toast.show { opacity: 1; transform: translateX(-50%); }
</style>