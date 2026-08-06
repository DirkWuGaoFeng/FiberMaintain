<template>
  <div class="clarify-card">
    <div class="clarify-header">
      <el-icon color="var(--fa-warning)"><QuestionFilled /></el-icon>
      <span class="clarify-title">{{ $t('chat.clarification') }}</span>
    </div>

    <p class="clarify-hint">{{ $t('chat.clarificationHint') }}</p>

    <!-- 澄清内容 -->
    <div class="clarify-content markdown-body" v-html="renderedContent" />

    <!-- 快捷回复选项 -->
    <div v-if="suggestions.length > 0" class="clarify-suggestions">
      <el-button
        v-for="(s, idx) in suggestions"
        :key="idx"
        size="small"
        round
        @click="emit('reply', s)"
      >
        {{ s }}
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 参数澄清卡片 — Agent 请求用户补充信息时展示
 * 从澄清文本中提取可能的快捷回复选项
 */
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps<{
  content: string
}>()

const emit = defineEmits<{ reply: [text: string] }>()

const renderedContent = computed(() => {
  return marked.parse(props.content, { breaks: true }) as string
})

/** 从内容中提取建议回复（识别 "如：xxx" / "例如 xxx" / 列表项模式） */
const suggestions = computed(() => {
  const results: string[] = []
  const text = props.content

  // 匹配 "如：FIBER-3" / "例如: 3" 模式
  const examplePattern = /(?:如|例如|比如)[：:]\s*([^\n，。,;；]+)/g
  let match: RegExpExecArray | null
  while ((match = examplePattern.exec(text)) !== null && results.length < 3) {
    results.push(match[1].trim())
  }

  // 匹配 "- xxx" 列表项
  if (results.length === 0) {
    const listPattern = /^[-•]\s+(.+)$/gm
    while ((match = listPattern.exec(text)) !== null && results.length < 4) {
      const item = match[1].trim()
      if (item.length <= 30) results.push(item)
    }
  }

  return results
})
</script>

<style scoped lang="scss">
.clarify-card {
  padding: 4px 0;

  .clarify-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;

    .el-icon {
      font-size: 16px;
    }

    .clarify-title {
      font-size: 13px;
      font-weight: 700;
      color: var(--fa-warning);
      letter-spacing: 0.3px;
    }
  }

  .clarify-hint {
    font-size: 12px;
    color: var(--fa-text-muted);
    margin: 0 0 8px;
  }

  .clarify-content {
    font-size: 13px;
    line-height: 1.7;
    color: var(--fa-text-primary);
    padding: 8px 12px;
    background: rgba(230, 162, 60, 0.06);
    border-radius: 6px;
    border: 1px dashed rgba(230, 162, 60, 0.3);
  }

  .clarify-suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 10px;

    .el-button {
      transition: transform 0.15s, box-shadow 0.15s;

      &:hover {
        transform: translateY(-1px);
        box-shadow: 0 2px 8px rgba(230, 162, 60, 0.2);
      }
    }
  }
}
</style>
