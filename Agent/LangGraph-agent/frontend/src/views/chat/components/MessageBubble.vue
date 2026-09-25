<template>
  <div class="message-bubble" :class="[message.role, { clarification: message.isClarification }]">
    <!-- 用户消息 -->
    <div v-if="message.role === 'user'" class="user-row">
      <div class="bubble user-bubble">{{ message.content }}</div>
      <div class="avatar user-avatar">我</div>
    </div>

    <!-- AI 消息 -->
    <div v-else class="ai-row">
      <div class="avatar ai-avatar">
        <svg viewBox="0 0 24 24" fill="none">
          <path d="M4 16 C9 16 9 8 14 8 H20" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
          <path d="M4 12 H20" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
          <path d="M4 8 C9 8 9 16 14 16 H20" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
        </svg>
      </div>
      <div class="bubble ai-bubble">
        <!-- 思考过程折叠面板 -->
        <ThinkingPanel
          v-if="message.thinkingSteps.length > 0"
          :steps="message.thinkingSteps"
          :tool-calls="message.toolCalls"
        />

        <!-- 工具调用卡片（无思考步骤时独立展示） -->
        <ToolCallCard
          v-if="message.toolCalls.length > 0 && message.thinkingSteps.length === 0"
          :tool-calls="message.toolCalls"
        />

        <!-- 澄清提示 -->
        <ClarifyCard v-if="message.isClarification" :content="message.content" @reply="emitReply" />

        <!-- 记忆事件注入（双层记忆细节层召回） -->
        <MemoryEventCard v-if="message.memoryEvents && message.memoryEvents.length > 0" :events="message.memoryEvents" />

        <!-- 正文内容（Markdown 渲染） -->
        <div
          v-if="message.content && !message.isClarification"
          class="markdown-body message-content"
          v-html="renderedContent"
        />

        <!-- 元信息 -->
        <div v-if="message.latencyMs && !message.streaming" class="message-meta">
          <el-tag size="small" type="info" effect="plain">{{ message.latencyMs }}ms</el-tag>
          <el-tag v-if="message.processingPath" size="small" effect="plain">
            {{ message.processingPath }}
          </el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 消息气泡 — 用户/AI 消息渲染 + Markdown + 思考链
 */
import { computed } from 'vue'
import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.min.css'
import type { ChatMessage } from '@/stores/chat'
import ThinkingPanel from './ThinkingPanel.vue'
import ToolCallCard from './ToolCallCard.vue'
import ClarifyCard from './ClarifyCard.vue'
import MemoryEventCard from './MemoryEventCard.vue'

const props = defineProps<{ message: ChatMessage }>()
const emit = defineEmits<{ reply: [text: string] }>()

// 配置 marked + highlight.js
marked.setOptions({
  breaks: true,
  gfm: true,
})

const renderer = new marked.Renderer()
renderer.code = function ({ text, lang }: { text: string; lang?: string }) {
  const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
  const highlighted = hljs.highlight(text, { language }).value
  return `<pre><code class="hljs language-${language}">${highlighted}</code></pre>`
}

const renderedContent = computed(() => {
  if (!props.message.content) return ''
  return marked.parse(props.message.content, { renderer }) as string
})

function emitReply(text: string) {
  emit('reply', text)
}
</script>

<style scoped lang="scss">
.message-bubble {
  margin-bottom: 20px;
  animation: msg-in 0.3s ease;

  &.user {
    .user-row {
      display: flex;
      justify-content: flex-end;
      align-items: flex-start;
      gap: 10px;
    }

    .user-bubble {
      max-width: 70%;
      background: var(--fa-accent);
      color: #fff;
      border-radius: 16px 16px 4px 16px;
      padding: 10px 16px;
      font-size: 14px;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .user-avatar {
      background: linear-gradient(135deg, #667eea, #764ba2);
      color: #fff;
    }
  }

  &.ai {
    .ai-row {
      display: flex;
      align-items: flex-start;
      gap: 10px;
    }

    .ai-bubble {
      max-width: 80%;
      min-width: 120px;
      background: var(--fa-bg-secondary);
      border: 1px solid var(--fa-border-color);
      border-radius: 4px 16px 16px 16px;
      padding: 12px 16px;
      box-shadow: var(--fa-shadow);
    }

    .ai-avatar {
      background: linear-gradient(135deg, #1a1a2e, #16213e);
      color: #3fd0ff;
      border: 1px solid rgba(63, 208, 255, 0.3);

      svg {
        width: 18px;
        height: 18px;
      }
    }
  }

  &.clarification .ai-bubble {
    border-color: var(--fa-warning);
    border-left: 3px solid var(--fa-warning);
  }
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}

.message-content {
  font-size: 14px;
}

.message-meta {
  display: flex;
  gap: 6px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--fa-border-color);
}

@keyframes msg-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
