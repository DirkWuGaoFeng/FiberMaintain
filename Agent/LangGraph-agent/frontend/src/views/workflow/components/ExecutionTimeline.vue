<template>
  <div class="execution-timeline">
    <div v-if="workflowStore.executions.length === 0" class="empty-hint">
      <el-icon :size="28" color="var(--fa-text-muted)"><Timer /></el-icon>
      <p>{{ $t('workflow.noExecution') }}</p>
    </div>

    <div v-else class="timeline-list">
      <div
        v-for="(exec, idx) in reversedExecutions"
        :key="idx"
        class="timeline-item"
        :class="exec.status"
      >
        <div class="item-marker">
          <span v-if="exec.status === 'running'" class="marker-dot running" />
          <span v-else-if="exec.status === 'completed'" class="marker-dot completed" />
          <span v-else class="marker-dot failed" />
          <span v-if="idx < reversedExecutions.length - 1" class="marker-line" />
        </div>

        <div class="item-content">
          <div class="item-header">
            <span class="node-name">{{ nodeLabel(exec.nodeId) }}</span>
            <el-tag v-if="exec.durationMs != null" size="small" type="info" effect="plain">
              {{ exec.durationMs }}ms
            </el-tag>
            <span v-else class="running-text">{{ $t('workflow.running') }}...</span>
          </div>
          <div class="item-time">{{ formatTime(exec.startTime) }}</div>

          <!-- 耗时条形图 -->
          <div v-if="exec.durationMs != null && maxDuration > 0" class="duration-bar">
            <div
              class="bar-fill"
              :style="{ width: `${(exec.durationMs / maxDuration) * 100}%` }"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- 总耗时 -->
    <div v-if="totalDuration > 0" class="total-duration">
      <span>{{ $t('workflow.duration') }}: {{ totalDuration }}ms</span>
      <span>{{ workflowStore.executions.length }} nodes</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 执行时序面板 — 节点执行顺序 + 耗时可视化
 */
import { computed } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'

const workflowStore = useWorkflowStore()

const reversedExecutions = computed(() => [...workflowStore.executions].reverse())

const maxDuration = computed(() =>
  Math.max(...workflowStore.executions.map((e) => e.durationMs || 0), 1),
)

const totalDuration = computed(() => {
  if (workflowStore.executions.length === 0) return 0
  const first = workflowStore.executions[0].startTime
  const lastEnd = Math.max(
    ...workflowStore.executions.map((e) => e.endTime || Date.now()),
  )
  return lastEnd - first
})

function nodeLabel(nodeId: string): string {
  const node = workflowStore.structure?.nodes.find((n) => n.id === nodeId)
  return node ? `${node.label}` : nodeId
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }) + '.' + String(ts % 1000).padStart(3, '0')
}
</script>

<style scoped lang="scss">
.execution-timeline {
  .empty-hint {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 40px 16px;
    text-align: center;

    p {
      font-size: 12px;
      color: var(--fa-text-muted);
      line-height: 1.6;
      margin: 0;
    }
  }

  .timeline-list {
    display: flex;
    flex-direction: column;
  }

  .timeline-item {
    display: flex;
    gap: 10px;
    min-height: 44px;

    .item-marker {
      display: flex;
      flex-direction: column;
      align-items: center;
      width: 14px;
      flex-shrink: 0;

      .marker-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        margin-top: 4px;
        flex-shrink: 0;

        &.running {
          background: var(--fa-accent);
          animation: pulse 1s infinite;
        }
        &.completed { background: var(--fa-success); }
        &.failed { background: var(--fa-danger); }
      }

      .marker-line {
        flex: 1;
        width: 2px;
        background: var(--fa-border-color);
        margin: 3px 0;
      }
    }

    .item-content {
      flex: 1;
      padding-bottom: 12px;
      min-width: 0;

      .item-header {
        display: flex;
        align-items: center;
        gap: 8px;

        .node-name {
          font-size: 12px;
          font-weight: 600;
          color: var(--fa-text-primary);
        }

        .running-text {
          font-size: 11px;
          color: var(--fa-accent);
        }
      }

      .item-time {
        font-size: 10px;
        color: var(--fa-text-muted);
        font-family: 'JetBrains Mono', monospace;
        margin-top: 2px;
      }

      .duration-bar {
        margin-top: 4px;
        height: 4px;
        background: var(--fa-bg-tertiary);
        border-radius: 2px;
        overflow: hidden;

        .bar-fill {
          height: 100%;
          background: linear-gradient(90deg, var(--fa-accent), #67c23a);
          border-radius: 2px;
          transition: width 0.3s ease;
        }
      }
    }
  }

  .total-duration {
    display: flex;
    justify-content: space-between;
    padding: 10px 4px;
    border-top: 1px dashed var(--fa-border-color);
    font-size: 11px;
    color: var(--fa-text-muted);
    font-weight: 600;
  }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
</style>
