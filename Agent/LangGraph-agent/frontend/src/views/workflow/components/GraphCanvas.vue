<template>
  <div class="graph-canvas">
    <VueFlow
      v-model:nodes="flowNodes"
      v-model:edges="flowEdges"
      :default-viewport="{ zoom: 0.85, x: 40, y: 20 }"
      :min-zoom="0.3"
      :max-zoom="2"
      fit-view-on-init
      class="fiber-flow"
      @node-click="handleNodeClick"
    >
      <template #node-graphNode="nodeProps">
        <GraphNode
          :data="nodeProps.data"
          :status="nodeProps.data.status"
          :selected="nodeProps.data.selected"
        />
      </template>

      <Background :gap="20" :size="1" pattern-color="var(--fa-border-color)" />
      <Controls position="bottom-left" />
      <MiniMap
        position="bottom-right"
        :node-color="miniMapColor"
        :mask-color="'rgba(0,0,0,0.08)'"
      />
    </VueFlow>

    <!-- 图例 -->
    <div class="graph-legend">
      <div class="legend-item"><span class="legend-dot idle" />{{ $t('workflow.idle') }}</div>
      <div class="legend-item"><span class="legend-dot running" />{{ $t('workflow.running') }}</div>
      <div class="legend-item"><span class="legend-dot completed" />{{ $t('workflow.completed') }}</div>
      <div class="legend-item"><span class="legend-dot failed" />{{ $t('workflow.failed') }}</div>
      <div class="legend-item edge-legend">
        <span class="legend-line solid" />{{ $t('workflow.graphStructure') }}
        <span class="legend-line dashed" />{{ $t('workflow.conditionalEdge') }}
        <span class="legend-line loop" />{{ $t('workflow.loopEdge') }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 图画布 — @vue-flow/core + dagre 自动布局
 * 实时映射 workflow store 节点状态到图节点样式
 */
import { ref, watch, onMounted } from 'vue'
import { VueFlow, useVueFlow, MarkerType } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import dagre from 'dagre'
import { useWorkflowStore } from '@/stores/workflow'
import GraphNode from './GraphNode.vue'
import type { Node as FlowNode, Edge as FlowEdge } from '@vue-flow/core'
import type { NodeStatus } from '@/types/graph'

import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

const props = defineProps<{
  selectedNode: string | null
}>()

const emit = defineEmits<{
  nodeClick: [nodeId: string]
}>()

const workflowStore = useWorkflowStore()
const { fitView } = useVueFlow()

const flowNodes = ref<FlowNode[]>([])
const flowEdges = ref<FlowEdge[]>([])

/** dagre 自动布局 */
function layoutGraph() {
  const structure = workflowStore.structure
  if (!structure) return

  const g = new dagre.graphlib.Graph({ multigraph: true })
  g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 80, marginx: 20, marginy: 20 })
  g.setDefaultEdgeLabel(() => ({}))

  const NODE_WIDTH = 172
  const NODE_HEIGHT = 64

  // 过滤掉 __start__ / __end__ 虚拟节点
  const realNodes = structure.nodes.filter((n) => n.id !== '__start__' && n.id !== '__end__')

  realNodes.forEach((node) => {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  })

  structure.edges
    .filter((e) => e.source !== '__start__' && e.target !== '__end__')
    .forEach((edge, idx) => {
      g.setEdge(edge.source, edge.target, {}, `e-${idx}`)
    })

  dagre.layout(g)

  // 生成 Flow 节点
  flowNodes.value = realNodes.map((node) => {
    const pos = g.node(node.id)
    return {
      id: node.id,
      type: 'graphNode',
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      data: {
        label: node.label,
        nodeType: node.type,
        description: node.description || '',
        status: workflowStore.nodeStatuses[node.id] || 'idle',
        selected: props.selectedNode === node.id,
      },
      style: { width: `${NODE_WIDTH}px`, height: `${NODE_HEIGHT}px` },
    }
  }) as FlowNode[]

  // 生成 Flow 边
  flowEdges.value = structure.edges
    .filter((e) => e.source !== '__start__' && e.target !== '__end__')
    .map((edge, idx) => ({
      id: `edge-${idx}`,
      source: edge.source,
      target: edge.target,
      label: edge.label || '',
      animated: edge.isLoop || false,
      style: {
        stroke: edge.isLoop
          ? 'var(--fa-danger)'
          : edge.conditional
            ? 'var(--fa-warning)'
            : 'var(--fa-text-muted)',
        strokeDasharray: edge.conditional ? '6 3' : undefined,
        strokeWidth: edge.isLoop ? 2 : 1.2,
      },
      labelStyle: { fontSize: 9, fill: 'var(--fa-text-muted)' },
      labelBgStyle: { fill: 'var(--fa-bg-primary)', opacity: 0.8 },
      markerEnd: { type: MarkerType.ArrowClosed, color: edge.isLoop ? 'var(--fa-danger)' : 'var(--fa-text-muted)' },
    })) as FlowEdge[]
}

/** 监听节点状态变化，更新节点样式 */
watch(
  () => workflowStore.nodeStatuses,
  (statuses) => {
    flowNodes.value = flowNodes.value.map((node) => ({
      ...node,
      data: {
        ...node.data,
        status: statuses[node.id] || 'idle',
        selected: props.selectedNode === node.id,
      },
    }))

    // 高亮正在执行的边
    flowEdges.value = flowEdges.value.map((edge) => {
      const sourceActive = statuses[edge.source] === 'completed'
      const targetActive = statuses[edge.target] === 'running'
      return {
        ...edge,
        animated: targetActive || (edge.data?.isLoop as boolean) || false,
        style: {
          ...edge.style,
          strokeWidth: sourceActive && targetActive ? 2.5 : ((edge.style as Record<string, unknown>)?.strokeWidth as number) || 1.2,
        },
      }
    }) as FlowEdge[]
  },
  { deep: true },
)

/** 监听选中节点变化 */
watch(
  () => props.selectedNode,
  (selected) => {
    flowNodes.value = flowNodes.value.map((node) => ({
      ...node,
      data: { ...node.data, selected: node.id === selected },
    }))
  },
)

function handleNodeClick(event: { node: FlowNode }) {
  emit('nodeClick', event.node.id)
}

function miniMapColor(node: FlowNode): string {
  const status = (node.data?.status as NodeStatus) || 'idle'
  const colors: Record<NodeStatus, string> = {
    idle: '#909399',
    running: '#409eff',
    completed: '#67c23a',
    failed: '#f56c6c',
    skipped: '#c0c4cc',
  }
  return colors[status]
}

onMounted(async () => {
  await workflowStore.loadStructure()
  layoutGraph()
  setTimeout(() => fitView({ padding: 0.15 }), 100)
})
</script>

<style scoped lang="scss">
.graph-canvas {
  width: 100%;
  height: 100%;
  position: relative;

  .fiber-flow {
    width: 100%;
    height: 100%;
    background: var(--fa-bg-primary);
  }
}

.graph-legend {
  position: absolute;
  top: 12px;
  left: 12px;
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 6px 12px;
  background: var(--fa-bg-secondary);
  border: 1px solid var(--fa-border-color);
  border-radius: 8px;
  font-size: 11px;
  color: var(--fa-text-muted);
  z-index: 5;
  flex-wrap: wrap;

  .legend-item {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .legend-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;

    &.idle { background: #909399; }
    &.running { background: #409eff; animation: pulse 1s infinite; }
    &.completed { background: #67c23a; }
    &.failed { background: #f56c6c; }
  }

  .legend-line {
    display: inline-block;
    width: 18px;
    height: 2px;
    margin-left: 6px;

    &.solid { background: var(--fa-text-muted); }
    &.dashed { background: repeating-linear-gradient(90deg, var(--fa-warning) 0 4px, transparent 4px 7px); }
    &.loop { background: var(--fa-danger); }
  }

  .edge-legend {
    gap: 2px;
  }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
