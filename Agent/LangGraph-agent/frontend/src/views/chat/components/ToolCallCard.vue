<template>
  <div class="tool-call-card">
    <div class="card-header" @click="expanded = !expanded">
      <el-icon class="chev" :class="{ rotated: expanded }"><ArrowRight /></el-icon>
      <span class="tool-icon">⚙️</span>
      <span class="card-title">{{ $t('chat.toolCalls') }}</span>
      <el-tag size="small" effect="plain" type="info">
        {{ $t('chat.toolCallCount', { count: toolCalls.length }) }}
      </el-tag>
      <!-- 运行状态摘要 -->
      <span v-if="runningCount > 0" class="status-dot running" />
      <span v-else-if="errorCount > 0" class="status-dot error" />
      <span v-else class="status-dot success" />
    </div>

    <transition name="slide-fade">
      <div v-show="expanded" class="card-body">
        <div
          v-for="tool in toolCalls"
          :key="tool.id"
          class="tool-item"
          :class="tool.status"
        >
          <div class="tool-item-header">
            <span class="tool-status-icon">
              <el-icon v-if="tool.status === 'running'" class="is-loading"><Loading /></el-icon>
              <el-icon v-else-if="tool.status === 'success'" color="var(--fa-success)"><CircleCheck /></el-icon>
              <el-icon v-else color="var(--fa-danger)"><CircleClose /></el-icon>
            </span>
            <code class="tool-name">{{ tool.name }}</code>
            <el-tag v-if="tool.endTime" size="small" type="info" effect="plain">
              {{ tool.endTime - tool.startTime }}ms
            </el-tag>
          </div>

          <!-- 参数 -->
          <div class="tool-args">
            <pre><code>{{ formatJson(tool.args) }}</code></pre>
          </div>

          <!-- 结果（可折叠） -->
          <div v-if="tool.result" class="tool-result">
            <div class="result-toggle" @click.stop="toggleResult(tool.id)">
              <el-icon :class="{ rotated: expandedResults.has(tool.id) }"><ArrowRight /></el-icon>
              <span>{{ $t('tools.result') }}</span>
            </div>
            <transition name="slide-fade">
              <pre v-show="expandedResults.has(tool.id)" class="result-content"><code>{{ tool.result }}</code></pre>
            </transition>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
/**
 * 工具调用卡片 — 展示 Agent 调用的工具序列、参数与结果
 */
import { ref, computed, reactive } from 'vue'
import type { ToolCallRecord } from '@/types/agent'

const props = defineProps<{
  toolCalls: ToolCallRecord[]
}>()

const expanded = ref(false)
const expandedResults = reactive(new Set<string>())

const runningCount = computed(() => props.toolCalls.filter((t) => t.status === 'running').length)
const errorCount = computed(() => props.toolCalls.filter((t) => t.status === 'error').length)

function toggleResult(id: string) {
  if (expandedResults.has(id)) {
    expandedResults.delete(id)
  } else {
    expandedResults.add(id)
  }
}

function formatJson(obj: Record<string, unknown>): string {
  const str = JSON.stringify(obj, null, 2)
  return str.length > 300 ? str.slice(0, 300) + '\n...' : str
}
</script>

<style scoped lang="scss">
.tool-call-card {
  margin-bottom: 10px;
  border: 1px solid var(--fa-border-color);
  border-radius: 8px;
  overflow: hidden;
  background: var(--fa-bg-tertiary);

  .card-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    cursor: pointer;
    user-select: none;
    transition: background 0.2s;

    &:hover {
      background: rgba(155, 89, 182, 0.06);
    }

    .chev {
      font-size: 12px;
      color: var(--fa-text-muted);
      transition: transform 0.25s ease;

      &.rotated {
        transform: rotate(90deg);
      }
    }

    .tool-icon {
      font-size: 14px;
    }

    .card-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--fa-text-secondary);
    }

    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      margin-left: auto;

      &.running {
        background: var(--fa-accent);
        animation: pulse 1s infinite;
      }
      &.success { background: var(--fa-success); }
      &.error { background: var(--fa-danger); }
    }
  }

  .card-body {
    padding: 8px 12px 12px;
    border-top: 1px solid var(--fa-border-color);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .tool-item {
    border: 1px solid var(--fa-border-color);
    border-radius: 6px;
    padding: 8px 10px;
    background: var(--fa-bg-secondary);
    border-left: 3px solid var(--fa-border-color);

    &.running { border-left-color: var(--fa-accent); }
    &.success { border-left-color: var(--fa-success); }
    &.error { border-left-color: var(--fa-danger); }

    .tool-item-header {
      display: flex;
      align-items: center;
      gap: 8px;

      .tool-name {
        font-size: 12px;
        font-weight: 600;
        color: var(--fa-text-primary);
        background: none;
        padding: 0;
      }
    }

    .tool-args {
      margin-top: 6px;

      pre {
        margin: 0;
        padding: 6px 8px;
        background: var(--fa-bg-tertiary);
        border-radius: 4px;
        overflow-x: auto;

        code {
          font-size: 11px;
          color: var(--fa-text-muted);
          line-height: 1.5;
        }
      }
    }

    .tool-result {
      margin-top: 6px;

      .result-toggle {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 11px;
        color: var(--fa-text-muted);
        cursor: pointer;

        &:hover { color: var(--fa-accent); }

        .el-icon {
          font-size: 10px;
          transition: transform 0.2s;

          &.rotated { transform: rotate(90deg); }
        }
      }

      .result-content {
        margin: 4px 0 0;
        padding: 6px 8px;
        background: var(--fa-bg-tertiary);
        border-radius: 4px;
        max-height: 150px;
        overflow-y: auto;

        code {
          font-size: 11px;
          color: var(--fa-text-secondary);
          white-space: pre-wrap;
          word-break: break-all;
        }
      }
    }
  }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.slide-fade-enter-active, .slide-fade-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}

.slide-fade-enter-from, .slide-fade-leave-to {
  opacity: 0;
  max-height: 0;
}

.slide-fade-enter-to, .slide-fade-leave-from {
  max-height: 800px;
}
</style>
