<template>
  <div class="memory-event-card">
    <div class="me-header">
      <el-icon color="var(--fa-primary)"><Memo /></el-icon>
      <span class="me-title">{{ $t('chat.memoryEvents') }}</span>
      <el-tag size="small" type="info" effect="plain">{{ events.length }}</el-tag>
    </div>

    <div class="me-list">
      <div v-for="(ev, idx) in events" :key="idx" class="me-item">
        <span class="me-type-tag" :class="typeClass(ev.event_type)">
          {{ typeLabel(ev.event_type) }}
        </span>
        <span class="me-value">{{ ev.details?.value || ev.details?.key || '—' }}</span>
        <el-tooltip
          v-if="typeof ev.similarity === 'number'"
          :content="$t('chat.memoryEventSimilarity')"
          placement="top"
        >
          <span class="me-sim">{{ (ev.similarity * 100).toFixed(0) }}%</span>
        </el-tooltip>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 记忆事件卡片 — 展示 result_aggregator 按当前问题召回的用户历史事件
 * （书籍 Ch3 双层记忆架构：概览层 preferences + 细节层事件语义检索）
 */
import type { MemoryEvent } from '@/types/agent'

defineProps<{ events: MemoryEvent[] }>()

function typeLabel(type: string): string {
  if (type.includes('fact')) return '事实'
  if (type.includes('activity')) return '活动'
  if (type.includes('preference')) return '偏好'
  return type.replace('memory.', '')
}

function typeClass(type: string): string {
  if (type.includes('fact')) return 'fact'
  if (type.includes('activity')) return 'activity'
  return 'preference'
}
</script>

<style scoped lang="scss">
.memory-event-card {
  margin: 8px 0;
  border: 1px solid var(--fa-border-color);
  border-left: 3px solid var(--fa-primary);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--fa-bg-secondary);

  .me-header {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 600;
    color: var(--fa-text-secondary);
    margin-bottom: 6px;
  }

  .me-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .me-item {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;

    .me-type-tag {
      flex-shrink: 0;
      padding: 1px 8px;
      border-radius: 4px;
      font-size: 11px;
      color: #fff;

      &.fact { background: #409eff; }
      &.activity { background: #67c23a; }
      &.preference { background: #e6a23c; }
    }

    .me-value {
      flex: 1;
      min-width: 0;
      color: var(--fa-text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .me-sim {
      flex-shrink: 0;
      font-size: 11px;
      color: var(--fa-text-muted);
      font-family: 'JetBrains Mono', monospace;
    }
  }
}
</style>
