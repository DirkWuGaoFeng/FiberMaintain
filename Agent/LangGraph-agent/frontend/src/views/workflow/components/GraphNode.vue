<template>
  <div class="graph-node" :class="[status, nodeType, { selected }]">
    <div class="node-type-bar" />
    <div class="node-body">
      <div class="node-header">
        <span class="node-icon">{{ typeIcon }}</span>
        <span class="node-label">{{ data.label }}</span>
      </div>
      <div class="node-footer">
        <span class="node-type-tag">{{ nodeType }}</span>
        <span v-if="status === 'running'" class="status-spinner" />
        <span v-else-if="status === 'completed'" class="status-check">✓</span>
        <span v-else-if="status === 'failed'" class="status-cross">✕</span>
      </div>
    </div>
    <el-tooltip :content="data.description" placement="top" :show-after="400">
      <div class="node-hover-area" />
    </el-tooltip>
  </div>
</template>

<script setup lang="ts">
/**
 * 自定义图节点 — 按类型着色 + 运行状态动效
 */
import { computed } from 'vue'
import type { NodeStatus, NodeType } from '@/types/graph'

const props = defineProps<{
  data: {
    label: string
    nodeType: NodeType
    description: string
    status: NodeStatus
    selected: boolean
  }
  status: NodeStatus
  selected: boolean
}>()

const nodeType = computed(() => props.data.nodeType)

const typeIcon = computed(() => {
  const icons: Record<NodeType, string> = {
    guard: '🛡',
    router: '⑂',
    executor: '⚡',
    subgraph: '◫',
    aggregator: '⊕',
    validator: '☑',
    generator: '✎',
  }
  return icons[props.data.nodeType] || '●'
})
</script>

<style scoped lang="scss">
.graph-node {
  width: 100%;
  height: 100%;
  border-radius: 8px;
  border: 1.5px solid var(--fa-border-color);
  background: var(--fa-bg-secondary);
  display: flex;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.15s;
  position: relative;

  &:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  }

  // 类型色条
  .node-type-bar {
    width: 4px;
    min-height: 100%;
    flex-shrink: 0;
  }

  &.guard .node-type-bar { background: #e6a23c; }
  &.router .node-type-bar { background: #409eff; }
  &.executor .node-type-bar { background: #67c23a; }
  &.subgraph .node-type-bar { background: #9b59b6; }
  &.aggregator .node-type-bar { background: #00b4d8; }
  &.validator .node-type-bar { background: #f39c12; }
  &.generator .node-type-bar { background: #e74c8b; }

  .node-body {
    flex: 1;
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-width: 0;
  }

  .node-header {
    display: flex;
    align-items: center;
    gap: 6px;

    .node-icon {
      font-size: 12px;
      flex-shrink: 0;
    }

    .node-label {
      font-size: 12px;
      font-weight: 700;
      color: var(--fa-text-primary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
  }

  .node-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;

    .node-type-tag {
      font-size: 9px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--fa-text-muted);
      background: var(--fa-bg-tertiary);
      padding: 1px 5px;
      border-radius: 3px;
    }

    .status-spinner {
      width: 10px;
      height: 10px;
      border: 2px solid rgba(64, 158, 255, 0.3);
      border-top-color: #409eff;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }

    .status-check {
      font-size: 11px;
      color: var(--fa-success);
      font-weight: 700;
    }

    .status-cross {
      font-size: 11px;
      color: var(--fa-danger);
      font-weight: 700;
    }
  }

  // 运行状态
  &.running {
    border-color: #409eff;
    box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.15), 0 0 12px rgba(64, 158, 255, 0.1);
    animation: node-glow 1.5s ease-in-out infinite;
  }

  &.completed {
    border-color: rgba(103, 194, 58, 0.6);
  }

  &.failed {
    border-color: rgba(245, 108, 108, 0.7);
    background: rgba(245, 108, 108, 0.04);
  }

  &.selected {
    border-color: var(--fa-accent);
    box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.2);
  }

  .node-hover-area {
    position: absolute;
    inset: 0;
  }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes node-glow {
  0%, 100% { box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.15); }
  50% { box-shadow: 0 0 0 5px rgba(64, 158, 255, 0.25), 0 0 16px rgba(64, 158, 255, 0.15); }
}
</style>
