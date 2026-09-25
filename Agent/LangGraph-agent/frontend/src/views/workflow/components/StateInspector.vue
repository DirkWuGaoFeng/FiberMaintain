<template>
  <div class="state-inspector">
    <!-- 选中节点详情 -->
    <div v-if="selectedNode" class="node-detail">
      <div class="detail-header">
        <span class="detail-title">{{ nodeDef?.label || selectedNode }}</span>
        <el-tag :type="statusType" size="small" effect="dark">{{ statusLabel }}</el-tag>
      </div>
      <p v-if="nodeDef?.description" class="detail-desc">{{ nodeDef.description }}</p>
      <div class="detail-meta">
        <div class="meta-row">
          <span class="meta-key">ID</span>
          <code class="meta-val">{{ selectedNode }}</code>
        </div>
        <div class="meta-row">
          <span class="meta-key">Type</span>
          <span class="meta-val">{{ nodeDef?.type || '-' }}</span>
        </div>
        <div v-if="lastExecution" class="meta-row">
          <span class="meta-key">{{ $t('workflow.duration') }}</span>
          <span class="meta-val">{{ lastExecution.durationMs ?? '—' }}ms</span>
        </div>
      </div>
    </div>

    <div v-else class="select-hint">
      <el-icon :size="24" color="var(--fa-text-muted)"><Pointer /></el-icon>
      <p>{{ $t('workflow.selectNode') }}</p>
    </div>

    <!-- 线程状态 -->
    <div class="thread-state">
      <div class="section-title">{{ $t('workflow.threadState') }}</div>

      <div class="state-grid">
        <div class="state-card">
          <span class="state-label">Thread</span>
          <code class="state-value thread-id">{{ chatStore.currentThreadId }}</code>
        </div>
        <div class="state-card">
          <span class="state-label">Intent</span>
          <span class="state-value">{{ threadState?.intent || '—' }}</span>
        </div>
        <div class="state-card">
          <span class="state-label">Path</span>
          <el-tag size="small" effect="plain">{{ threadState?.processingPath || 'normal' }}</el-tag>
        </div>
        <div class="state-card">
          <span class="state-label">Loop</span>
          <span class="state-value">{{ workflowStore.loopState.loopCount }} / {{ workflowStore.loopState.maxLoops }}</span>
        </div>
        <div class="state-card">
          <span class="state-label">Degradation</span>
          <el-tag size="small" :type="degradationType">L{{ threadState?.degradationLevel ?? 0 }}</el-tag>
        </div>
        <div class="state-card">
          <span class="state-label">Nodes</span>
          <span class="state-value">{{ workflowStore.completedCount }} ✓</span>
        </div>
      </div>

      <!-- 刷新线程状态 -->
      <el-button size="small" text class="refresh-btn" :loading="loading" @click="loadState">
        <el-icon><Refresh /></el-icon> {{ $t('common.refresh') }}
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 状态检查器 — 节点详情 + 线程状态快照
 */
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkflowStore } from '@/stores/workflow'
import { useChatStore } from '@/stores/chat'
import { getThreadState } from '@/api/threads'
import type { ThreadState } from '@/types/graph'

const props = defineProps<{
  selectedNode: string | null
}>()

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const chatStore = useChatStore()

const threadState = ref<ThreadState | null>(null)
const loading = ref(false)

const nodeDef = computed(() =>
  workflowStore.structure?.nodes.find((n) => n.id === props.selectedNode),
)

const lastExecution = computed(() => {
  if (!props.selectedNode) return null
  return [...workflowStore.executions].reverse().find((e) => e.nodeId === props.selectedNode)
})

const statusType = computed(() => {
  const status = workflowStore.nodeStatuses[props.selectedNode || ''] || 'idle'
  const map: Record<string, 'info' | 'primary' | 'success' | 'danger'> = {
    idle: 'info', running: 'primary', completed: 'success', failed: 'danger', skipped: 'info',
  }
  return map[status] || 'info'
})

const statusLabel = computed(() => {
  const status = workflowStore.nodeStatuses[props.selectedNode || ''] || 'idle'
  return t(`workflow.${status}`)
})

const degradationType = computed(() => {
  const level = threadState.value?.degradationLevel ?? 0
  if (level === 0) return 'success'
  if (level <= 2) return 'warning'
  return 'danger'
})

async function loadState() {
  loading.value = true
  try {
    threadState.value = await getThreadState(chatStore.currentThreadId)
  } catch {
    // 后端不可用
  } finally {
    loading.value = false
  }
}

watch(() => props.selectedNode, () => { /* 触发响应式更新 */ })
</script>

<style scoped lang="scss">
.state-inspector {
  .node-detail {
    padding: 12px;
    border: 1px solid var(--fa-border-color);
    border-radius: 8px;
    background: var(--fa-bg-tertiary);
    margin-bottom: 16px;

    .detail-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 6px;

      .detail-title {
        font-size: 14px;
        font-weight: 700;
        color: var(--fa-text-primary);
      }
    }

    .detail-desc {
      font-size: 12px;
      color: var(--fa-text-secondary);
      margin: 0 0 10px;
      line-height: 1.5;
    }

    .detail-meta {
      display: flex;
      flex-direction: column;
      gap: 4px;

      .meta-row {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 11px;

        .meta-key {
          color: var(--fa-text-muted);
          width: 50px;
          flex-shrink: 0;
        }

        .meta-val {
          color: var(--fa-text-secondary);
          font-size: 11px;
        }
      }
    }
  }

  .select-hint {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 24px 0;

    p {
      font-size: 12px;
      color: var(--fa-text-muted);
      margin: 0;
    }
  }

  .thread-state {
    .section-title {
      font-size: 12px;
      font-weight: 700;
      color: var(--fa-text-secondary);
      margin-bottom: 10px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .state-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;

      .state-card {
        padding: 8px 10px;
        border: 1px solid var(--fa-border-color);
        border-radius: 6px;
        background: var(--fa-bg-primary);
        display: flex;
        flex-direction: column;
        gap: 4px;

        .state-label {
          font-size: 10px;
          color: var(--fa-text-muted);
          font-weight: 600;
          text-transform: uppercase;
        }

        .state-value {
          font-size: 12px;
          font-weight: 600;
          color: var(--fa-text-primary);

          &.thread-id {
            font-size: 10px;
            word-break: break-all;
          }
        }
      }
    }

    .refresh-btn {
      margin-top: 10px;
      width: 100%;
    }
  }
}
</style>
