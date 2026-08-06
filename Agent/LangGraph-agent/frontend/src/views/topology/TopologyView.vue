<template>
  <div class="topology-view">
    <!-- 工具栏 -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">{{ $t('topology.title') }}</h2>
        <el-tag size="small" effect="plain" type="info">
          {{ topologyStore.fibers.length }} fibers · {{ topologyStore.neContainers.length }} NEs
        </el-tag>
      </div>
      <div class="header-right">
        <!-- 视图模式切换 -->
        <el-radio-group :model-value="topologyStore.viewMode" size="small" @change="handleModeChange">
          <el-radio-button value="full">{{ $t('topology.fullMode') }}</el-radio-button>
          <el-radio-button value="colored">{{ $t('topology.coloredMode') }}</el-radio-button>
        </el-radio-group>
        <!-- 图例 -->
        <div class="legend">
          <span class="legend-item"><i class="dot red" />{{ $t('topology.red') }}</span>
          <span class="legend-item"><i class="dot yellow" />{{ $t('topology.yellow') }}</span>
          <span class="legend-item"><i class="dot green" />{{ $t('topology.green') }}</span>
        </div>
        <el-button-group size="small">
          <el-button @click="zoomIn"><el-icon><ZoomIn /></el-icon></el-button>
          <el-button @click="zoomOut"><el-icon><ZoomOut /></el-icon></el-button>
          <el-button @click="resetView">{{ $t('topology.resetView') }}</el-button>
        </el-button-group>
        <el-button size="small" :loading="topologyStore.loading" @click="refreshData">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- SVG 拓扑画布 -->
    <div class="topo-canvas" ref="canvasRef">
      <div v-if="topologyStore.loading && topologyStore.fibers.length === 0" class="canvas-loading">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
        <span>{{ $t('common.loading') }}</span>
      </div>
      <div v-else-if="topologyStore.fibers.length === 0" class="canvas-empty">
        {{ $t('common.noData') }}
      </div>

      <svg
        v-show="topologyStore.fibers.length > 0"
        class="topo-svg"
        :viewBox="viewBox"
        @wheel.prevent="handleWheel"
        @mousedown="startPan"
        @mousemove="doPan"
        @mouseup="endPan"
        @mouseleave="endPan"
      >
        <defs>
          <filter id="glow-red" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="glow-yellow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        <!-- 网元容器层 -->
        <g class="ne-layer">
          <g v-for="ne in topologyStore.neContainers" :key="ne.ne_id" class="ne-container">
            <rect
              :x="ne.x" :y="ne.y"
              :width="ne.width" :height="ne.height"
              rx="8" ry="8"
              class="ne-rect"
              :class="{ highlighted: hoveredNe === ne.ne_id }"
            />
            <text :x="ne.x + 10" :y="ne.y + 18" class="ne-label">{{ ne.label }}</text>
          </g>
        </g>

        <!-- 网元内部连纤层（场景2） -->
        <g class="internal-fibers-layer">
          <template v-for="[fiberId, scene] in scene2Entries" :key="'int-' + fiberId">
            <path
              v-for="intFiber in scene.ne_internal_fibers"
              :key="'if-' + intFiber.fiber_id"
              :d="internalEdgePath(intFiber)"
              class="internal-edge"
            />
          </template>
        </g>

        <!-- 网元间连纤层 -->
        <g class="edges-layer">
          <path
            v-for="edge in topologyStore.topoEdges"
            :key="edge.fiber.fiber_id"
            :d="fiberEdgePath(edge.fiber)"
            class="fiber-edge"
            :class="[`edge-${edge.color.toLowerCase()}`, { highlighted: isEdgeHighlighted(edge.fiber) }]"
            :filter="edge.color === 'RED' ? 'url(#glow-red)' : edge.color === 'YELLOW' ? 'url(#glow-yellow)' : undefined"
            @mouseenter="showTooltip($event, edge)"
            @mousemove="moveTooltip($event)"
            @mouseleave="hideTooltip"
          />
        </g>

        <!-- 板卡节点层 -->
        <g class="boards-layer">
          <g
            v-for="ne in topologyStore.neContainers"
            :key="'b-' + ne.ne_id"
          >
            <g
              v-for="board in ne.boards"
              :key="board.board_id"
              class="board-node"
              :class="{ passive: board.is_passive, active: hoveredBoard === board.board_id }"
              @mouseenter="hoveredBoard = board.board_id"
              @mouseleave="hoveredBoard = null"
            >
              <rect
                :x="board.x - 32" :y="board.y - 18"
                width="64" height="36"
                rx="5" ry="5"
                class="board-rect"
              />
              <text :x="board.x" :y="board.y - 3" class="board-id">B{{ board.board_id }}</text>
              <text :x="board.x" :y="board.y + 11" class="board-type">
                {{ board.is_passive ? 'P' : 'A' }}
              </text>
            </g>
          </g>
        </g>
      </svg>

      <!-- 悬停详情浮层 -->
      <Transition name="tooltip-fade">
        <div
          v-if="tooltip.visible"
          class="edge-tooltip"
          :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }"
        >
          <div class="tooltip-header">
            <span class="tooltip-fiber-id">Fiber #{{ tooltip.edge?.fiber.fiber_id }}</span>
            <el-tag :type="tooltipTagType" size="small" effect="dark">{{ tooltipColorLabel }}</el-tag>
          </div>
          <div class="tooltip-rows">
            <div class="tooltip-row">
              <span class="row-label">{{ $t('topology.srcBoard') }}</span>
              <span class="row-value">B{{ tooltip.edge?.fiber.src_board_id }} / P{{ tooltip.edge?.fiber.src_port_id }}</span>
            </div>
            <div class="tooltip-row">
              <span class="row-label">{{ $t('topology.srcNe') }}</span>
              <span class="row-value">NE-{{ tooltip.edge?.fiber.src_ne_id }}</span>
            </div>
            <div class="tooltip-row">
              <span class="row-label">{{ $t('topology.dstBoard') }}</span>
              <span class="row-value">B{{ tooltip.edge?.fiber.dst_board_id }} / P{{ tooltip.edge?.fiber.dst_port_id }}</span>
            </div>
            <div class="tooltip-row">
              <span class="row-label">{{ $t('topology.dstNe') }}</span>
              <span class="row-value">NE-{{ tooltip.edge?.fiber.dst_ne_id }}</span>
            </div>
            <div v-if="tooltipSceneType > 0" class="tooltip-row">
              <span class="row-label">{{ $t('topology.sceneType') }}</span>
              <span class="row-value">{{ tooltipSceneType === 2 ? $t('topology.scene2') : $t('topology.scene1') }}</span>
            </div>
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 连纤拓扑图 — 平铺层级式布局
 * 网元容器(NE) → 板卡节点(Board) → 连纤边(Fiber)
 * 支持场景2网元内部拓扑、有色/全网模式切换、悬停详情、异常链路动画
 */
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTopologyStore } from '@/stores/topology'
import type { FiberInfo, TopoEdge, TopoViewMode, FiberSceneDetail } from '@/types/topology'

const { t } = useI18n()
const topologyStore = useTopologyStore()

const canvasRef = ref<HTMLElement | null>(null)

// ===== 缩放与平移 =====
const scale = ref(1)
const panX = ref(0)
const panY = ref(0)
const isPanning = ref(false)
const panStart = reactive({ x: 0, y: 0, px: 0, py: 0 })

const BASE_W = 1200
const BASE_H = 800

const viewBox = computed(() => {
  const w = BASE_W / scale.value
  const h = BASE_H / scale.value
  const x = (BASE_W - w) / 2 - panX.value / scale.value
  const y = (BASE_H - h) / 2 - panY.value / scale.value
  return `${x} ${y} ${w} ${h}`
})

function zoomIn() { scale.value = Math.min(4, scale.value * 1.3) }
function zoomOut() { scale.value = Math.max(0.3, scale.value / 1.3) }
function resetView() { scale.value = 1; panX.value = 0; panY.value = 0 }

function handleWheel(e: WheelEvent) {
  const factor = e.deltaY < 0 ? 1.12 : 0.89
  scale.value = Math.max(0.3, Math.min(4, scale.value * factor))
}

function startPan(e: MouseEvent) {
  isPanning.value = true
  panStart.x = e.clientX
  panStart.y = e.clientY
  panStart.px = panX.value
  panStart.py = panY.value
}

function doPan(e: MouseEvent) {
  if (!isPanning.value) return
  panX.value = panStart.px + (e.clientX - panStart.x)
  panY.value = panStart.py + (e.clientY - panStart.y)
}

function endPan() { isPanning.value = false }

// ===== 视图模式 =====
function handleModeChange(val: string | number | boolean | undefined) {
  if (val) topologyStore.setViewMode(val as TopoViewMode)
}

// ===== 交互状态 =====
const hoveredBoard = ref<number | null>(null)
const hoveredNe = ref<number | null>(null)

/** 场景2详情条目（用于模板渲染） */
const scene2Entries = computed<[number, FiberSceneDetail][]>(() => {
  return [...topologyStore.sceneDetails.entries()].filter(([, s]) => s.scene_type === 2)
})

// ===== 边路径计算 =====

/** 网元间连纤路径（板卡到板卡的贝塞尔曲线） */
function fiberEdgePath(fiber: FiberInfo): string {
  const src = topologyStore.boardPosMap.get(fiber.src_board_id)
  const dst = topologyStore.boardPosMap.get(fiber.dst_board_id)
  if (!src || !dst) return ''

  const dx = dst.x - src.x
  const dy = dst.y - src.y
  const dist = Math.sqrt(dx * dx + dy * dy) || 1

  // 控制点偏移（基于 fiber_id 避免平行边重叠）
  const offset = ((fiber.fiber_id % 5) - 2) * 12
  const mx = (src.x + dst.x) / 2 + (-dy / dist) * (30 + offset)
  const my = (src.y + dst.y) / 2 + (dx / dist) * (30 + offset)

  return `M ${src.x} ${src.y} Q ${mx} ${my} ${dst.x} ${dst.y}`
}

/** 网元内部连纤路径（场景2，较短的弧线） */
function internalEdgePath(fiber: FiberInfo): string {
  const src = topologyStore.boardPosMap.get(fiber.src_board_id)
  const dst = topologyStore.boardPosMap.get(fiber.dst_board_id)
  if (!src || !dst) return ''

  const mx = (src.x + dst.x) / 2
  const my = (src.y + dst.y) / 2 - 15
  return `M ${src.x} ${src.y} Q ${mx} ${my} ${dst.x} ${dst.y}`
}

/** 悬停板卡时高亮相连连纤 */
function isEdgeHighlighted(fiber: FiberInfo): boolean {
  if (hoveredBoard.value === null) return false
  return fiber.src_board_id === hoveredBoard.value || fiber.dst_board_id === hoveredBoard.value
}

// ===== 悬停详情浮层 =====
const tooltip = reactive({
  visible: false,
  x: 0,
  y: 0,
  edge: null as TopoEdge | null,
})

const tooltipTagType = computed<'danger' | 'warning' | 'success'>(() => {
  const c = tooltip.edge?.color
  if (c === 'RED') return 'danger'
  if (c === 'YELLOW') return 'warning'
  return 'success'
})

const tooltipColorLabel = computed(() => {
  const c = tooltip.edge?.color
  if (c === 'RED') return t('topology.red')
  if (c === 'YELLOW') return t('topology.yellow')
  return t('topology.green')
})

const tooltipSceneType = computed(() => {
  if (!tooltip.edge) return 0
  return topologyStore.sceneTypeMap.get(tooltip.edge.fiber.fiber_id) ?? 0
})

function showTooltip(e: MouseEvent, edge: TopoEdge) {
  tooltip.edge = edge
  tooltip.visible = true
  positionTooltip(e)
}

function moveTooltip(e: MouseEvent) {
  positionTooltip(e)
}

function positionTooltip(e: MouseEvent) {
  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return
  tooltip.x = e.clientX - rect.left + 14
  tooltip.y = e.clientY - rect.top - 10
  if (tooltip.x > rect.width - 260) tooltip.x = e.clientX - rect.left - 270
}

function hideTooltip() {
  tooltip.visible = false
  tooltip.edge = null
}

// ===== 数据加载 =====
async function refreshData() {
  await Promise.allSettled([
    topologyStore.fetchAllFibers(),
    topologyStore.fetchColoredFibers(),
    topologyStore.fetchRealtimeStats(),
  ])
  // 加载场景2详情
  await topologyStore.fetchAllScene2Details()
}

onMounted(() => {
  refreshData()
  topologyStore.startPolling()
})

onUnmounted(() => {
  topologyStore.stopPolling()
})
</script>

<style scoped lang="scss">
.topology-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px 20px;
  gap: 12px;
  overflow: hidden;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;

  .header-left {
    display: flex;
    align-items: center;
    gap: 12px;

    .page-title {
      margin: 0;
      font-size: 16px;
      font-weight: 700;
      color: var(--fa-text-primary);
    }
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 12px;

    .legend {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 11px;
      color: var(--fa-text-secondary);

      .legend-item {
        display: flex;
        align-items: center;
        gap: 4px;

        .dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          &.red { background: #f56c6c; }
          &.yellow { background: #e6a23c; }
          &.green { background: #67c23a; }
        }
      }
    }
  }
}

.topo-canvas {
  position: relative;
  flex: 1;
  min-height: 0;
  border: 1px solid var(--fa-border-color);
  border-radius: 10px;
  background:
    radial-gradient(circle at 50% 50%, rgba(64, 158, 255, 0.03) 0%, transparent 70%),
    var(--fa-bg-secondary);
  overflow: hidden;

  .canvas-loading,
  .canvas-empty {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    font-size: 12px;
    color: var(--fa-text-muted);
  }
}

.topo-svg {
  width: 100%;
  height: 100%;
  cursor: grab;
  &:active { cursor: grabbing; }
}

// ===== 网元容器 =====
.ne-container {
  .ne-rect {
    fill: var(--fa-bg-primary);
    stroke: var(--fa-border-color);
    stroke-width: 1.5;
    transition: stroke 0.15s, stroke-width 0.15s;

    &.highlighted {
      stroke: #409eff;
      stroke-width: 2.5;
    }
  }

  .ne-label {
    font-size: 12px;
    font-weight: 700;
    fill: var(--fa-text-primary);
    pointer-events: none;
  }
}

// ===== 板卡节点 =====
.board-node {
  cursor: pointer;

  .board-rect {
    fill: var(--fa-bg-secondary);
    stroke: #409eff;
    stroke-width: 1.5;
    transition: stroke-width 0.15s, fill 0.15s;
  }

  .board-id {
    text-anchor: middle;
    font-size: 10px;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    fill: var(--fa-text-primary);
    pointer-events: none;
  }

  .board-type {
    text-anchor: middle;
    font-size: 9px;
    font-weight: 600;
    fill: var(--fa-text-muted);
    pointer-events: none;
  }

  &.passive .board-rect {
    stroke: #e6a23c;
    stroke-dasharray: 4 2;
  }

  &.active .board-rect,
  &:hover .board-rect {
    stroke-width: 3;
    fill: rgba(64, 158, 255, 0.06);
  }
}

// ===== 连纤边 =====
.fiber-edge {
  fill: none;
  stroke-width: 2.5;
  stroke-linecap: round;
  cursor: pointer;
  transition: stroke-width 0.15s, opacity 0.15s;

  &.edge-green {
    stroke: #67c23a;
    opacity: 0.7;
  }

  &.edge-yellow {
    stroke: #e6a23c;
    stroke-dasharray: 8 4;
    animation: dash-flow 1.2s linear infinite;
  }

  &.edge-red {
    stroke: #f56c6c;
    stroke-width: 3;
    stroke-dasharray: 10 5;
    animation: dash-flow 0.7s linear infinite;
  }

  &.highlighted {
    stroke-width: 4.5;
    opacity: 1 !important;
  }

  &:hover {
    stroke-width: 5;
    opacity: 1;
  }
}

// ===== 网元内部连纤（场景2） =====
.internal-edge {
  fill: none;
  stroke: #909399;
  stroke-width: 1.5;
  stroke-dasharray: 5 3;
  opacity: 0.7;
  pointer-events: none;
}

@keyframes dash-flow {
  to { stroke-dashoffset: -30; }
}

// ===== 悬停详情浮层 =====
.edge-tooltip {
  position: absolute;
  z-index: 100;
  min-width: 230px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--fa-border-color);
  background: var(--fa-bg-primary);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  pointer-events: none;

  .tooltip-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;

    .tooltip-fiber-id {
      font-size: 12px;
      font-weight: 800;
      font-family: 'JetBrains Mono', monospace;
      color: var(--fa-text-primary);
    }
  }

  .tooltip-rows {
    display: flex;
    flex-direction: column;
    gap: 4px;

    .tooltip-row {
      display: flex;
      justify-content: space-between;
      gap: 14px;

      .row-label {
        font-size: 10px;
        color: var(--fa-text-muted);
        flex-shrink: 0;
      }

      .row-value {
        font-size: 10px;
        font-weight: 600;
        font-family: 'JetBrains Mono', monospace;
        color: var(--fa-text-secondary);
      }
    }
  }
}

.tooltip-fade-enter-active,
.tooltip-fade-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}
.tooltip-fade-enter-from,
.tooltip-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}
</style>
