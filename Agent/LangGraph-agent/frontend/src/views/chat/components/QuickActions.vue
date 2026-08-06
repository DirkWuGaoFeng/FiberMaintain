<template>
  <div class="quick-actions">
    <div class="actions-label">{{ $t('chat.quickActions') }}</div>
    <div class="actions-grid">
      <button
        v-for="action in actions"
        :key="action.text"
        class="action-chip"
        :style="{ '--chip-color': action.color }"
        @click="emit('select', action.text)"
      >
        <span class="chip-icon">{{ action.icon }}</span>
        <span class="chip-text">{{ action.label }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 快捷指令面板 — 常用查询一键触发
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const emit = defineEmits<{ select: [text: string] }>()
const { t } = useI18n()

interface QuickAction {
  icon: string
  label: string
  text: string
  color: string
}

const actions = computed<QuickAction[]>(() => [
  {
    icon: '🔍',
    label: t('chat.quickActionItems.spanloss'),
    text: t('chat.quickActionTexts.spanloss'),
    color: '#409eff',
  },
  {
    icon: '🚨',
    label: t('chat.quickActionItems.alarm'),
    text: t('chat.quickActionTexts.alarm'),
    color: '#f56c6c',
  },
  {
    icon: '🎨',
    label: t('chat.quickActionItems.color'),
    text: t('chat.quickActionTexts.color'),
    color: '#e6a23c',
  },
  {
    icon: '📊',
    label: t('chat.quickActionItems.trend'),
    text: t('chat.quickActionTexts.trend'),
    color: '#67c23a',
  },
  {
    icon: '🏥',
    label: t('chat.quickActionItems.health'),
    text: t('chat.quickActionTexts.health'),
    color: '#9b59b6',
  },
  {
    icon: '📋',
    label: t('chat.quickActionItems.report'),
    text: t('chat.quickActionTexts.report'),
    color: '#00b4d8',
  },
])
</script>

<style scoped lang="scss">
.quick-actions {
  margin-top: 20px;
  width: 100%;
  max-width: 560px;

  .actions-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--fa-text-muted);
    text-align: center;
    margin-bottom: 12px;
    letter-spacing: 1px;
  }

  .actions-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;

    @media (max-width: 640px) {
      grid-template-columns: repeat(2, 1fr);
    }
  }

  .action-chip {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 14px 10px;
    border: 1px solid var(--fa-border-color);
    border-radius: 10px;
    background: var(--fa-bg-secondary);
    cursor: pointer;
    transition: all 0.2s ease;
    position: relative;
    overflow: hidden;

    &::before {
      content: '';
      position: absolute;
      inset: 0;
      background: var(--chip-color);
      opacity: 0;
      transition: opacity 0.2s;
    }

    &:hover {
      border-color: var(--chip-color);
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);

      &::before {
        opacity: 0.05;
      }
    }

    &:active {
      transform: translateY(0) scale(0.97);
    }

    .chip-icon {
      font-size: 20px;
      position: relative;
      z-index: 1;
    }

    .chip-text {
      font-size: 12px;
      font-weight: 500;
      color: var(--fa-text-secondary);
      position: relative;
      z-index: 1;
      text-align: center;
      line-height: 1.3;
    }
  }
}
</style>
