<template>
  <div class="thinking-panel">
    <div class="panel-header" @click="expanded = !expanded">
      <el-icon class="chev" :class="{ rotated: expanded }"><ArrowRight /></el-icon>
      <span class="panel-title">🧠 {{ $t('chat.thinkingProcess') }}</span>
      <el-tag size="small" type="info" effect="plain">{{ steps.length + toolCalls.length }}</el-tag>
      <!-- 心跳状态指示 -->
      <span v-if="heartbeatMs > 0" class="heartbeat-indicator">
        ⏳ 处理中... {{ (heartbeatMs / 1000).toFixed(0) }}s
      </span>
    </div>

    <transition name="collapse">
      <div v-show="expanded" class="panel-body">
        <el-timeline class="think-timeline">
          <!-- 思考步骤 -->
          <el-timeline-item
            v-for="(step, idx) in steps"
            :key="'step-' + idx"
            :type="stepColor(step.type)"
            :hollow="true"
            size="normal"
          >
            <div class="step-item">
              <div class="step-title">
                <span class="step-type-badge" :class="step.type">{{ stepTypeLabel(step.type) }}</span>
                {{ step.title }}
                <!-- 节点耗时显示 -->
                <el-tag v-if="stepDuration(step)" size="small" type="info" effect="plain">
                  {{ stepDuration(step) }}ms
                </el-tag>
              </div>
              <div class="step-content" :class="{ 'error-text': isErrorStep(step) }">
                {{ step.content }}
              </div>

              <!-- 意图识别详情 -->
              <div v-if="step.type === 'intent' && intentData(step)" class="step-detail">
                <el-tag size="small" effect="dark" type="primary">{{ intentData(step)?.intent }}</el-tag>
                <span class="confidence">
                  {{ $t('chat.confidence') }}: {{ ((intentData(step)?.confidence ?? 0) * 100).toFixed(0) }}%
                </span>
                <span v-if="intentData(step)?.fiberIds?.length" class="fiber-ids">
                  Fiber: {{ intentData(step)?.fiberIds?.join(', ') }}
                </span>
              </div>

              <!-- 分析结论详情 -->
              <div v-if="step.type === 'analysis' && analysisData(step)" class="step-detail">
                <el-tag size="small" :type="severityType(analysisData(step)?.severity ?? 'NORMAL')">
                  {{ analysisData(step)?.severity }}
                </el-tag>
                <span class="confidence">
                  {{ $t('chat.confidence') }}: {{ ((analysisData(step)?.confidence ?? 0) * 100).toFixed(0) }}%
                </span>
                <ul v-if="analysisData(step)?.evidence?.length" class="evidence-list">
                  <li v-for="(ev, i) in analysisData(step)?.evidence" :key="i">{{ ev }}</li>
                </ul>
              </div>

              <!-- 规则判定详情 -->
              <div v-if="step.type === 'rule_judgment' && judgmentData(step)" class="step-detail">
                <el-tag size="small" :type="severityType(judgmentData(step)?.status ?? 'NORMAL')">
                  {{ judgmentData(step)?.status }}
                </el-tag>
                <ul v-if="judgmentData(step)?.findings?.length" class="evidence-list">
                  <li v-for="(f, i) in judgmentData(step)?.findings" :key="i">{{ f }}</li>
                </ul>
                <div v-if="judgmentData(step)?.suggestedActions?.length" class="actions-list">
                  <strong>{{ $t('chat.suggestedActions') }}:</strong>
                  <ul>
                    <li v-for="(a, i) in judgmentData(step)?.suggestedActions" :key="i">{{ a }}</li>
                  </ul>
                </div>
              </div>

              <!-- 错误信息高亮 -->
              <div v-if="stepError(step)" class="step-error">
                ❌ {{ stepError(step) }}
              </div>
            </div>
          </el-timeline-item>

          <!-- 工具调用 -->
          <el-timeline-item
            v-for="tool in toolCalls"
            :key="'tool-' + tool.id"
            :type="tool.status === 'error' ? 'danger' : 'success'"
            :hollow="true"
            size="normal"
          >
            <div class="step-item tool-step">
              <div class="step-title">
                <span class="step-type-badge tool">TOOL</span>
                {{ tool.name }}
                <el-tag v-if="tool.endTime" size="small" type="info" effect="plain">
                  {{ tool.endTime - tool.startTime }}ms
                </el-tag>
              </div>
              <div class="tool-args">
                <code>{{ formatArgs(tool.args) }}</code>
              </div>
              <div v-if="tool.result" class="tool-result">{{ tool.result }}</div>
            </div>
          </el-timeline-item>
        </el-timeline>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
/**
 * 思考过程面板 — LLM 思维链 / 决策过程 / 工具调用序列可视化
 * v7.1: 添加节点耗时显示、错误高亮、心跳状态
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ThinkingStep, ToolCallRecord, IntentResult, AnalysisVerdict, RuleJudgment } from '@/types/agent'

const props = defineProps<{
  steps: ThinkingStep[]
  toolCalls: ToolCallRecord[]
  /** 心跳已经过时间 (ms)，0 表示无心跳 */
  heartbeatMs?: number
}>()

const { t } = useI18n()
const expanded = ref(false)

/** 计算步骤耗时（如果 data 中包含 duration_ms） */
function stepDuration(step: ThinkingStep): number | null {
  const data = step.data as Record<string, unknown> | undefined
  if (data && typeof data.duration_ms === 'number') {
    return Math.round(data.duration_ms)
  }
  return null
}

/** 判断是否为错误步骤 */
function isErrorStep(step: ThinkingStep): boolean {
  const data = step.data as Record<string, unknown> | undefined
  return !!(data?.error || step.content.includes('失败') || step.content.includes('ERROR'))
}

/** 提取步骤错误信息 */
function stepError(step: ThinkingStep): string | null {
  const data = step.data as Record<string, unknown> | undefined
  if (data?.error) return String(data.error)
  return null
}

function stepColor(type: ThinkingStep['type']): 'primary' | 'success' | 'warning' | 'danger' | 'info' {
  switch (type) {
    case 'intent': return 'primary'
    case 'analysis': return 'warning'
    case 'rule_judgment': return 'success'
    case 'validation': return 'info'
    case 'loop': return 'danger'
    default: return 'info'
  }
}

function stepTypeLabel(type: ThinkingStep['type']): string {
  const labels: Record<string, string> = {
    intent: 'LLM',
    rule_judgment: 'RULE',
    analysis: 'LLM',
    loop: 'LOOP',
    routing: 'ROUTE',
    validation: 'CHECK',
  }
  return labels[type] || 'INFO'
}

function severityType(severity: string): 'success' | 'warning' | 'danger' {
  if (severity === 'CRITICAL') return 'danger'
  if (severity === 'WARNING') return 'warning'
  return 'success'
}

function intentData(step: ThinkingStep): IntentResult | null {
  return (step.data as IntentResult) ?? null
}

function analysisData(step: ThinkingStep): AnalysisVerdict | null {
  return (step.data as AnalysisVerdict) ?? null
}

function judgmentData(step: ThinkingStep): RuleJudgment | null {
  return (step.data as RuleJudgment) ?? null
}

function formatArgs(args: Record<string, unknown>): string {
  const str = JSON.stringify(args)
  return str.length > 120 ? str.slice(0, 120) + '...' : str
}

// 避免 unused 警告
void t
</script>

<style scoped lang="scss">
.thinking-panel {
  margin-bottom: 10px;
  border: 1px solid var(--fa-border-color);
  border-radius: 8px;
  overflow: hidden;
  background: var(--fa-bg-tertiary);

  .panel-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    cursor: pointer;
    user-select: none;
    transition: background 0.2s;

    &:hover {
      background: rgba(64, 158, 255, 0.06);
    }

    .chev {
      font-size: 12px;
      transition: transform 0.25s ease;
      color: var(--fa-text-muted);

      &.rotated {
        transform: rotate(90deg);
      }
    }

    .panel-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--fa-text-secondary);
    }

    .heartbeat-indicator {
      margin-left: auto;
      font-size: 11px;
      color: var(--fa-warning, #e6a23c);
      animation: pulse 1.5s ease-in-out infinite;
    }
  }

  .panel-body {
    padding: 4px 12px 12px;
    border-top: 1px solid var(--fa-border-color);
  }

  .think-timeline {
    padding-top: 12px;

    :deep(.el-timeline-item__wrapper) {
      padding-left: 18px;
    }

    :deep(.el-timeline-item) {
      padding-bottom: 12px;
    }
  }

  .step-item {
    .step-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      font-weight: 600;
      color: var(--fa-text-primary);
      flex-wrap: wrap;
    }

    .step-type-badge {
      font-size: 10px;
      font-weight: 700;
      padding: 1px 6px;
      border-radius: 4px;
      letter-spacing: 0.5px;

      &.intent, &.analysis { background: rgba(64, 158, 255, 0.15); color: var(--fa-accent); }
      &.rule_judgment { background: rgba(103, 194, 58, 0.15); color: var(--fa-success); }
      &.loop { background: rgba(245, 108, 108, 0.15); color: var(--fa-danger); }
      &.routing, &.validation { background: rgba(144, 147, 153, 0.15); color: var(--fa-text-muted); }
      &.tool { background: rgba(155, 89, 182, 0.15); color: #9b59b6; }
    }

    .step-content {
      margin-top: 4px;
      font-size: 12px;
      color: var(--fa-text-secondary);
      line-height: 1.5;

      &.error-text {
        color: var(--fa-danger);
        font-weight: 500;
      }
    }

    .step-error {
      margin-top: 6px;
      padding: 6px 10px;
      background: rgba(245, 108, 108, 0.1);
      border-radius: 4px;
      border-left: 3px solid var(--fa-danger);
      font-size: 12px;
      color: var(--fa-danger);
      word-break: break-all;
    }

    .step-detail {
      margin-top: 6px;
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      font-size: 12px;

      .confidence {
        color: var(--fa-text-muted);
      }

      .fiber-ids {
        color: var(--fa-text-muted);
        font-family: monospace;
      }

      .evidence-list, .actions-list ul {
        width: 100%;
        padding-left: 16px;
        margin: 4px 0;
        color: var(--fa-text-secondary);
        font-size: 12px;
        line-height: 1.6;
      }

      .actions-list strong {
        font-size: 12px;
        color: var(--fa-text-secondary);
      }
    }

    &.tool-step {
      .tool-args {
        margin-top: 4px;

        code {
          font-size: 11px;
          background: var(--fa-bg-secondary);
          padding: 2px 6px;
          border-radius: 4px;
          color: var(--fa-text-muted);
          word-break: break-all;
        }
      }

      .tool-result {
        margin-top: 4px;
        font-size: 11px;
        color: var(--fa-text-muted);
        max-height: 60px;
        overflow-y: auto;
        white-space: pre-wrap;
        word-break: break-all;
      }
    }
  }
}

.collapse-enter-active, .collapse-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}

.collapse-enter-from, .collapse-leave-to {
  opacity: 0;
  max-height: 0;
}

.collapse-enter-to, .collapse-leave-from {
  max-height: 600px;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
