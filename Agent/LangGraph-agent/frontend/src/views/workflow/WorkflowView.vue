<template>
  <div class="workflow-view">
    <!-- 顶部工具栏 -->
    <div class="wf-toolbar">
      <div class="toolbar-left">
        <h2 class="page-title">{{ $t('workflow.title') }}</h2>
        <el-tag v-if="workflowStore.isExecuting" type="primary" effect="dark" size="small" class="exec-badge">
          <span class="pulse-dot" /> {{ $t('workflow.running') }}
        </el-tag>
        <el-tag v-else-if="workflowStore.completedCount > 0" type="success" effect="plain" size="small">
          {{ $t('workflow.completed') }} · {{ workflowStore.completedCount }} nodes
        </el-tag>
      </div>
      <div class="toolbar-right">
        <el-tag effect="plain" size="small" type="info">
          {{ $t('workflow.totalNodes') }}: {{ workflowStore.structure?.nodes.length ?? 19 }}
        </el-tag>
        <el-button size="small" text @click="handleReset">
          <el-icon><RefreshRight /></el-icon> {{ $t('common.reset') }}
        </el-button>
      </div>
    </div>

    <div class="wf-content">
      <!-- 图画布 -->
      <div class="graph-area">
        <GraphCanvas
          :selected-node="selectedNode"
          @node-click="selectedNode = $event"
        />
      </div>

      <!-- 右侧面板 -->
      <div class="side-panel" :class="{ collapsed: panelCollapsed }">
        <div class="panel-toggle" @click="panelCollapsed = !panelCollapsed">
          <el-icon><component :is="panelCollapsed ? 'ArrowLeft' : 'ArrowRight'" /></el-icon>
        </div>

        <template v-if="!panelCollapsed">
          <el-tabs v-model="activeTab" class="panel-tabs">
            <el-tab-pane :label="$t('workflow.executionTimeline')" name="timeline">
              <ExecutionTimeline />
            </el-tab-pane>
            <el-tab-pane :label="$t('workflow.stateInspector')" name="state">
              <StateInspector :selected-node="selectedNode" />
            </el-tab-pane>
            <el-tab-pane :label="$t('workflow.loopMonitor')" name="loop">
              <LoopMonitor />
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 工作流可视化主页 — LangGraph 18 节点图实时状态
 */
import { ref, onMounted } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import GraphCanvas from './components/GraphCanvas.vue'
import ExecutionTimeline from './components/ExecutionTimeline.vue'
import StateInspector from './components/StateInspector.vue'
import LoopMonitor from './components/LoopMonitor.vue'

const workflowStore = useWorkflowStore()

const selectedNode = ref<string | null>(null)
const activeTab = ref('timeline')
const panelCollapsed = ref(false)

function handleReset() {
  workflowStore.resetExecution()
  selectedNode.value = null
}

onMounted(() => {
  workflowStore.loadStructure()
  workflowStore.bindGraphEvents()
})
</script>

<style scoped lang="scss">
.workflow-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.wf-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--fa-border-color);
  background: var(--fa-bg-secondary);

  .toolbar-left {
    display: flex;
    align-items: center;
    gap: 12px;

    .page-title {
      font-size: 16px;
      font-weight: 700;
      margin: 0;
      color: var(--fa-text-primary);
    }

    .exec-badge {
      .pulse-dot {
        display: inline-block;
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: #fff;
        margin-right: 4px;
        animation: pulse 1s infinite;
      }
    }
  }

  .toolbar-right {
    display: flex;
    align-items: center;
    gap: 8px;
  }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.wf-content {
  flex: 1;
  display: flex;
  min-height: 0;
}

.graph-area {
  flex: 1;
  min-width: 0;
  position: relative;
}

.side-panel {
  width: 340px;
  min-width: 340px;
  border-left: 1px solid var(--fa-border-color);
  background: var(--fa-bg-secondary);
  display: flex;
  flex-direction: column;
  position: relative;
  transition: width 0.25s ease, min-width 0.25s ease;

  &.collapsed {
    width: 0;
    min-width: 0;
    border-left: none;
    overflow: hidden;
  }

  .panel-toggle {
    position: absolute;
    left: -24px;
    top: 50%;
    transform: translateY(-50%);
    width: 24px;
    height: 48px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--fa-bg-secondary);
    border: 1px solid var(--fa-border-color);
    border-right: none;
    border-radius: 6px 0 0 6px;
    cursor: pointer;
    z-index: 10;
    color: var(--fa-text-muted);
    transition: color 0.2s;

    &:hover {
      color: var(--fa-accent);
    }
  }

  .panel-tabs {
    height: 100%;
    display: flex;
    flex-direction: column;

    :deep(.el-tabs__header) {
      margin: 0;
      padding: 0 12px;
    }

    :deep(.el-tabs__content) {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
    }
  }
}
</style>
