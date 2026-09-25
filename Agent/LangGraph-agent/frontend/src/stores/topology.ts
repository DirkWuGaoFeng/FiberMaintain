/**
 * 连纤拓扑状态管理 — 全量拓扑 / 颜色统计 / 趋势数据 / 场景详情 / WebSocket 事件处理
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getFiberStatsRealtime, getFiberStatsTrend, getAllColoredFibers, batchGetFibers, getFiberScene } from '@/api/fiber'
import type {
  FiberInfo, ColoredFiber, FiberStatsRealtime, TrendPoint, TrendRange,
  TopoNode, TopoEdge, FiberColor, TopoViewMode, FiberSceneDetail,
  NeContainer, BoardNode,
} from '@/types/topology'
import type { FiberColorEvent, FiberStatsEvent } from '@/types/events'

const STATS_POLL_INTERVAL = 30000

/** 时间范围 → 毫秒偏移 */
const RANGE_MS: Record<TrendRange, number> = {
  hour: 60 * 60 * 1000,
  day: 24 * 60 * 60 * 1000,
  week: 7 * 24 * 60 * 60 * 1000,
}

/** 布局常量 */
const NE_COLS = 3
const NE_PADDING = 20
const NE_HEADER = 28
const BOARD_W = 64
const BOARD_H = 36
const BOARD_GAP = 14
const NE_MARGIN_X = 60
const NE_MARGIN_Y = 50

export const useTopologyStore = defineStore('topology', () => {
  // ===== 状态 =====
  const fibers = ref<FiberInfo[]>([])
  const coloredFibers = ref<ColoredFiber[]>([])
  const stats = ref<FiberStatsRealtime | null>(null)
  const trendPoints = ref<TrendPoint[]>([])
  const trendRange = ref<TrendRange>('day')
  const loading = ref(false)
  const lastStatsUpdate = ref<number | null>(null)

  /** 拓扑视图模式：colored=仅有颜色连纤, full=全网连纤 */
  const viewMode = ref<TopoViewMode>('full')
  /** 场景2详情缓存 (fiber_id → scene detail) */
  const sceneDetails = ref<Map<number, FiberSceneDetail>>(new Map())

  let pollTimer: ReturnType<typeof setInterval> | null = null

  // ===== 计算属性 =====
  const redCount = computed(() => stats.value?.red_count ?? 0)
  const yellowCount = computed(() => stats.value?.yellow_count ?? 0)
  const greenCount = computed(() => stats.value?.green_count ?? 0)

  /** 连纤颜色映射表（fiber_id → color） */
  const colorMap = computed(() => {
    const map = new Map<number, FiberColor>()
    for (const cf of coloredFibers.value) {
      map.set(cf.fiber.fiber_id, cf.color)
    }
    return map
  })

  /** 场景类型映射表（fiber_id → scenario_type） */
  const sceneTypeMap = computed(() => {
    const map = new Map<number, number>()
    for (const cf of coloredFibers.value) {
      if (cf.scenario_type > 0) map.set(cf.fiber.fiber_id, cf.scenario_type)
    }
    return map
  })

  /** 拓扑图节点（按网元聚合 — 保留旧接口兼容） */
  const topoNodes = computed<TopoNode[]>(() => {
    const neMap = new Map<number, Set<number>>()
    for (const f of fibers.value) {
      if (!neMap.has(f.src_ne_id)) neMap.set(f.src_ne_id, new Set())
      if (!neMap.has(f.dst_ne_id)) neMap.set(f.dst_ne_id, new Set())
      neMap.get(f.src_ne_id)!.add(f.src_board_id)
      neMap.get(f.dst_ne_id)!.add(f.dst_board_id)
    }

    const nodes: TopoNode[] = []
    const neIds = [...neMap.keys()].sort((a, b) => a - b)
    const count = neIds.length
    const cx = 500, cy = 350
    const rx = Math.min(380, 120 + count * 40)
    const ry = Math.min(260, 90 + count * 28)

    neIds.forEach((neId, i) => {
      const angle = (2 * Math.PI * i) / Math.max(count, 1) - Math.PI / 2
      nodes.push({
        id: neId,
        label: `NE-${neId}`,
        x: cx + rx * Math.cos(angle),
        y: cy + ry * Math.sin(angle),
        boardCount: neMap.get(neId)!.size,
      })
    })
    return nodes
  })

  /** 拓扑图边（根据 viewMode 过滤） */
  const topoEdges = computed<TopoEdge[]>(() => {
    return fibers.value
      .map((f) => ({
        fiber: f,
        color: colorMap.value.get(f.fiber_id) ?? 'GREEN' as FiberColor,
      }))
      .filter((edge) => {
        if (viewMode.value === 'colored') {
          return edge.color === 'RED' || edge.color === 'YELLOW'
        }
        return true
      })
  })

  /** 网元容器布局（平铺网格） */
  const neContainers = computed<NeContainer[]>(() => {
    // 按 ne_id 分组所有板卡
    const neMap = new Map<number, Set<number>>()
    for (const f of fibers.value) {
      if (!neMap.has(f.src_ne_id)) neMap.set(f.src_ne_id, new Set())
      if (!neMap.has(f.dst_ne_id)) neMap.set(f.dst_ne_id, new Set())
      neMap.get(f.src_ne_id)!.add(f.src_board_id)
      neMap.get(f.dst_ne_id)!.add(f.dst_board_id)
    }

    // 从场景详情中补充无源板卡
    for (const [, scene] of sceneDetails.value) {
      for (const pb of scene.passive_boards) {
        if (!neMap.has(pb.ne_id)) neMap.set(pb.ne_id, new Set())
        neMap.get(pb.ne_id)!.add(pb.board_id)
      }
    }

    const neIds = [...neMap.keys()].sort((a, b) => a - b)
    const containers: NeContainer[] = []

    neIds.forEach((neId, idx) => {
      const boardIds = [...neMap.get(neId)!].sort((a, b) => a - b)
      const col = idx % NE_COLS
      const row = Math.floor(idx / NE_COLS)

      // 计算容器尺寸
      const boardsPerRow = Math.min(boardIds.length, 4)
      const boardRows = Math.ceil(boardIds.length / boardsPerRow)
      const containerW = NE_PADDING * 2 + boardsPerRow * BOARD_W + (boardsPerRow - 1) * BOARD_GAP
      const containerH = NE_HEADER + NE_PADDING * 2 + boardRows * BOARD_H + (boardRows - 1) * BOARD_GAP

      // 容器位置（网格排列 + 间距）
      const cellW = containerW + NE_MARGIN_X
      const cellH = containerH + NE_MARGIN_Y
      const x = col * cellW + 40
      const y = row * cellH + 40

      // 板卡节点坐标
      const boards: BoardNode[] = boardIds.map((bid, bi) => {
        const bCol = bi % boardsPerRow
        const bRow = Math.floor(bi / boardsPerRow)
        // 判断是否为无源板卡（从场景详情中查找）
        let isPassive = false
        for (const [, scene] of sceneDetails.value) {
          if (scene.passive_boards.some((pb) => pb.board_id === bid)) {
            isPassive = true
            break
          }
        }
        return {
          board_id: bid,
          ne_id: neId,
          is_passive: isPassive,
          x: x + NE_PADDING + bCol * (BOARD_W + BOARD_GAP) + BOARD_W / 2,
          y: y + NE_HEADER + NE_PADDING + bRow * (BOARD_H + BOARD_GAP) + BOARD_H / 2,
        }
      })

      containers.push({
        ne_id: neId,
        label: `NE-${neId}`,
        x,
        y,
        width: containerW,
        height: containerH,
        boards,
      })
    })

    return containers
  })

  /** 板卡坐标查找表 */
  const boardPosMap = computed(() => {
    const map = new Map<number, { x: number; y: number }>()
    for (const container of neContainers.value) {
      for (const board of container.boards) {
        map.set(board.board_id, { x: board.x, y: board.y })
      }
    }
    return map
  })

  // ===== 动作 =====

  /** 获取全量连纤拓扑 */
  async function fetchAllFibers() {
    try {
      const { results } = await batchGetFibers()
      fibers.value = results
        .filter((r) => r.found && r.fiber)
        .map((r) => r.fiber!)
    } catch {
      // 后端不可用时保持现有数据
    }
  }

  /** 获取所有非绿色连纤 */
  async function fetchColoredFibers() {
    try {
      const { fibers: colored } = await getAllColoredFibers()
      coloredFibers.value = colored
    } catch {
      // 静默失败
    }
  }

  /** 拉取实时统计 */
  async function fetchRealtimeStats() {
    try {
      stats.value = await getFiberStatsRealtime(true)
      lastStatsUpdate.value = Date.now()
    } catch {
      // 静默失败
    }
  }

  /** 拉取趋势数据 */
  async function fetchTrend(range?: TrendRange) {
    if (range) trendRange.value = range
    const end = new Date()
    const start = new Date(end.getTime() - RANGE_MS[trendRange.value])
    const fmt = (d: Date) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
    try {
      const { points } = await getFiberStatsTrend(fmt(start), fmt(end))
      trendPoints.value = points
    } catch {
      // 静默失败
    }
  }

  /** 按需获取连纤场景详情（场景2时获取网元内部拓扑） */
  async function fetchSceneDetail(fiberId: number) {
    if (sceneDetails.value.has(fiberId)) return
    try {
      const { found, scene } = await getFiberScene(fiberId)
      if (found && scene) {
        sceneDetails.value.set(fiberId, scene)
        // 触发响应式更新
        sceneDetails.value = new Map(sceneDetails.value)
      }
    } catch {
      // 静默失败
    }
  }

  /** 批量获取所有场景2连纤的详情 */
  async function fetchAllScene2Details() {
    const scene2Fibers = coloredFibers.value.filter((cf) => cf.scenario_type === 2)
    await Promise.allSettled(scene2Fibers.map((cf) => fetchSceneDetail(cf.fiber.fiber_id)))
  }

  /** 加载全部数据（页面初始化时调用） */
  async function fetchAll() {
    loading.value = true
    await Promise.allSettled([fetchAllFibers(), fetchColoredFibers(), fetchRealtimeStats(), fetchTrend()])
    loading.value = false
  }

  /** 切换视图模式 */
  function setViewMode(mode: TopoViewMode) {
    viewMode.value = mode
  }

  /** 处理 WebSocket 颜色变更事件 */
  function handleColorEvent(event: FiberColorEvent) {
    const idx = coloredFibers.value.findIndex((cf) => cf.fiber.fiber_id === event.fiber_id)
    if (event.new_color === 'GREEN') {
      if (idx !== -1) coloredFibers.value.splice(idx, 1)
    } else {
      if (idx !== -1) {
        coloredFibers.value[idx] = { ...coloredFibers.value[idx], color: event.new_color }
      } else {
        const fiber = fibers.value.find((f) => f.fiber_id === event.fiber_id)
        if (fiber) {
          coloredFibers.value.push({ fiber, color: event.new_color, scenario_type: 0 })
        }
      }
    }
    if (stats.value) {
      const delta = { RED: 0, YELLOW: 0, GREEN: 0 }
      delta[event.old_color]--
      delta[event.new_color]++
      stats.value = {
        ...stats.value,
        red_count: Math.max(0, stats.value.red_count + delta.RED),
        yellow_count: Math.max(0, stats.value.yellow_count + delta.YELLOW),
        green_count: Math.max(0, stats.value.green_count + delta.GREEN),
        total_colored: Math.max(0, stats.value.red_count + delta.RED + stats.value.yellow_count + delta.YELLOW),
      }
    }
  }

  /** 处理 WebSocket 统计更新事件 */
  function handleStatsEvent(event: FiberStatsEvent) {
    const d = event.data
    stats.value = {
      total_fibers: d.total_fibers ?? stats.value?.total_fibers ?? 0,
      red_count: d.red_count ?? stats.value?.red_count ?? 0,
      yellow_count: d.yellow_count ?? stats.value?.yellow_count ?? 0,
      green_count: d.green_count ?? stats.value?.green_count ?? 0,
      total_colored: (d.red_count ?? 0) + (d.yellow_count ?? 0),
      active_alarms: stats.value?.active_alarms ?? 0,
    }
    lastStatsUpdate.value = Date.now()
  }

  /** 启动统计轮询 */
  function startPolling() {
    if (pollTimer) return
    fetchRealtimeStats()
    pollTimer = setInterval(fetchRealtimeStats, STATS_POLL_INTERVAL)
  }

  /** 停止统计轮询 */
  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  return {
    // 状态
    fibers,
    coloredFibers,
    stats,
    trendPoints,
    trendRange,
    loading,
    lastStatsUpdate,
    viewMode,
    sceneDetails,
    // 计算属性
    redCount,
    yellowCount,
    greenCount,
    colorMap,
    sceneTypeMap,
    topoNodes,
    topoEdges,
    neContainers,
    boardPosMap,
    // 动作
    fetchAllFibers,
    fetchColoredFibers,
    fetchRealtimeStats,
    fetchTrend,
    fetchSceneDetail,
    fetchAllScene2Details,
    fetchAll,
    setViewMode,
    handleColorEvent,
    handleStatsEvent,
    startPolling,
    stopPolling,
  }
})
