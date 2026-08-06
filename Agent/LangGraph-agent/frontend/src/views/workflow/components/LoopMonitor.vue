<template>
  <div class="loop-monitor">
    <div class="section-title">{{ $t('workflow.safeguard') }} (4)</div>

    <!-- 四重终止保护仪表盘 -->
    <div class="safeguard-list">
      <!-- ① 轮次上限 -->
      <div class="safeguard-item" :class="{ warning: loopRatio > 0.66, danger: loopRatio >= 1 }">
        <div class="safeguard-header">
          <span class="safeguard-name">① {{ $t('workflow.roundLimit') }}</span>
          <span class="safeguard-value">{{ loop.loopCount }} / {{ loop.maxLoops }}</span>
        </div>
        <el-progress
          :percentage="loopRatio * 100"
          :stroke-width="6"
          :color="progressColor(loopRatio)"
          :show-text="false"
        />
      </div>

      <!-- ② LLM 预算 -->
      <div class="safeguard-item" :class="{ warning: llmRatio > 0.7, danger: llmRatio >= 1 }">
        <div class="safeguard-header">
          <span class="safeguard-name">② {{ $t('workflow.llmBudget') }}</span>
          <span class="safeguard-value">{{ loop.llmCallCount }} / {{ loop.maxLlmCalls }}</span>
        </div>
        <el-progress
          :percentage="llmRatio * 100"
          :stroke-width="6"
          :color="progressColor(llmRatio)"
          :show-text="false"
        />
      </div>

      <!-- ③ 无进展检测 -->
      <div class="safeguard-item" :class="{ warning: noProgressRatio > 0.5, danger: noProgressRatio >= 1 }">
        <div class="safeguard-header">
          <span class="safeguard-name">③ {{ $t('workflow.noProgress') }}</span>
          <span class="safeguard-value">{{ loop.noProgressCount }} / {{ loop.maxNoProgress }}</span>
        </div>
        <el-progress
          :percentage="noProgressRatio * 100"
          :stroke-width="6"
          :color="progressColor(noProgressRatio)"
          :show-text="false"
        />
      </div>

      <!-- ④ 工具熔断 -->
      <div class="safeguard-item circuit" :class="{ danger: loop.circuitBreakerOpen }">
        <div class="safeguard-header">
          <span class="safeguard-name">④ {{ $t('workflow.circuitBreaker') }}</span>
          <el-tag :type="loop.circuitBreakerOpen ? 'danger' : 'success'" size="small" effect="dark">
            {{ loop.circuitBreakerOpen ? 'OPEN' : 'CLOSED' }}
          </el-tag>
        </div>
        <div class="circuit-desc">连续失败 ≥5 次触发熔断，30s 冷却</div>
      </div>
    </div>

    <!-- 循环历史 -->
    <div class="loop-history">
      <div class="section-title">{{ $t('workflow.currentLoop') }}</div>
      <div v-if="loopRecords.length === 0" class="no-loops">
        {{ $t('common.noData') }}
      </div>
      <div v-else class="loop-records">
        <div v-for="record in loopRecords" :key="record.loopNumber" class="loop-record">
          <el-tag size="small" type="warning" effect="plain">
            {{ $t('chat.loopRound', { n: record.loopNumber }) }}
          </el-tag>
          <span class="record-reason">{{ record.reason }}</span>
          <code class="record-tool">{{ record.toolRequested }}</code>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 循环监控面板 — 4 重终止保护实时状态
 */
import { computed } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import type { LoopRecord } from '@/types/agent'

const workflowStore = useWorkflowStore()

const loop = computed(() => workflowStore.loopState)

const loopRatio = computed(() => loop.value.loopCount / loop.value.maxLoops)
const llmRatio = computed(() => loop.value.llmCallCount / loop.value.maxLlmCalls)
const noProgressRatio = computed(() => loop.value.noProgressCount / loop.value.maxNoProgress)

/** 从执行记录中推断循环（data_collector 重复执行即为循环） */
const loopRecords = computed<LoopRecord[]>(() => {
  const collectorRuns = workflowStore.executions.filter((e) => e.nodeId === 'data_collector')
  return collectorRuns.slice(1).map((run, idx) => ({
    loopNumber: idx + 1,
    reason: 'analysis_expert → need_more_data',
    toolRequested: 'data_collector (ReAct)',
    timestamp: new Date(run.startTime).toISOString(),
  }))
})

function progressColor(ratio: number): string {
  if (ratio >= 1) return '#f56c6c'
  if (ratio > 0.66) return '#e6a23c'
  return '#67c23a'
}
</script>

<style scoped lang="scss">
.loop-monitor {
  .section-title {
    font-size: 12px;
    font-weight: 700;
    color: var(--fa-text-secondary);
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .safeguard-list {
    display: flex;
    flex-direction: column;
    gap: 14px;
    margin-bottom: 20px;
  }

  .safeguard-item {
    padding: 10px 12px;
    border: 1px solid var(--fa-border-color);
    border-radius: 8px;
    background: var(--fa-bg-primary);
    transition: border-color 0.3s;

    &.warning {
      border-color: rgba(230, 162, 60, 0.5);
    }

    &.danger {
      border-color: rgba(245, 108, 108, 0.6);
      background: rgba(245, 108, 108, 0.03);
    }

    .safeguard-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 8px;

      .safeguard-name {
        font-size: 12px;
        font-weight: 600;
        color: var(--fa-text-primary);
      }

      .safeguard-value {
        font-size: 12px;
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
        color: var(--fa-text-secondary);
      }
    }

    &.circuit .circuit-desc {
      font-size: 11px;
      color: var(--fa-text-muted);
    }
  }

  .loop-history {
    .no-loops {
      font-size: 12px;
      color: var(--fa-text-muted);
      padding: 12px 0;
      text-align: center;
    }

    .loop-records {
      display: flex;
      flex-direction: column;
      gap: 8px;

      .loop-record {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 10px;
        border: 1px solid var(--fa-border-color);
        border-radius: 6px;
        flex-wrap: wrap;

        .record-reason {
          font-size: 11px;
          color: var(--fa-text-secondary);
        }

        .record-tool {
          font-size: 10px;
          color: var(--fa-text-muted);
          background: var(--fa-bg-tertiary);
          padding: 1px 5px;
          border-radius: 3px;
        }
      }
    }
  }
}
</style>
