<template>
  <div class="chat-view">
    <!-- 会话线程侧栏 -->
    <ThreadSidebar
      :visible="sidebarVisible"
      @close="sidebarVisible = false"
      @select="handleThreadSelect"
      @new-thread="handleNewThread"
    />

    <!-- 主对话区 -->
    <div class="chat-main">
      <!-- 消息列表 -->
      <div ref="messageContainer" class="message-area" @scroll="onScroll">
        <!-- 空状态 -->
        <div v-if="chatStore.messages.length === 0" class="empty-state">
          <div class="empty-icon">
            <svg viewBox="0 0 64 64" fill="none">
              <path d="M8 44 C24 44 24 20 40 20 H56" stroke="var(--fa-accent)" stroke-width="2.5" stroke-linecap="round" opacity="0.9"/>
              <path d="M8 32 H56" stroke="#4f8dff" stroke-width="2.5" stroke-linecap="round" opacity="0.7"/>
              <path d="M8 20 C24 20 24 44 40 44 H56" stroke="#2fd6a3" stroke-width="2.5" stroke-linecap="round" opacity="0.9"/>
              <circle cx="54" cy="32" r="4" fill="var(--fa-accent)">
                <animate attributeName="opacity" values="1;.3;1" dur="1.8s" repeatCount="indefinite"/>
              </circle>
            </svg>
          </div>
          <h3>{{ $t('chat.emptyState') }}</h3>
          <p class="text-muted">{{ $t('chat.emptyHint') }}</p>
          <QuickActions @select="handleQuickAction" />
        </div>

        <!-- 消息流 -->
        <MessageBubble
          v-for="msg in chatStore.messages"
          :key="msg.id"
          :message="msg"
          @reply="handleQuickReply"
        />

        <!-- 流式指示器 -->
        <div v-if="chatStore.isStreaming" class="streaming-indicator">
          <span class="dot" /><span class="dot" /><span class="dot" />
          <span class="text-muted">{{ $t('chat.streaming') }}</span>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-area">
        <div class="input-wrapper">
          <el-button
            class="sidebar-toggle"
            text
            circle
            @click="sidebarVisible = !sidebarVisible"
          >
            <el-icon><Menu /></el-icon>
          </el-button>

          <el-input
            v-model="inputText"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 5 }"
            :placeholder="$t('chat.placeholder')"
            resize="none"
            @keydown.enter.exact.prevent="handleSend"
          />

          <el-button
            v-if="chatStore.isStreaming"
            type="danger"
            circle
            class="send-btn"
            @click="chatStore.stopStreaming()"
          >
            <el-icon><VideoPause /></el-icon>
          </el-button>
          <el-button
            v-else
            type="primary"
            circle
            class="send-btn"
            :disabled="!inputText.trim()"
            @click="handleSend"
          >
            <el-icon><Promotion /></el-icon>
          </el-button>
        </div>
        <div class="input-hint text-muted">
          <span>Enter {{ $t('chat.send') }} · LangGraph v7.1 · {{ chatStore.currentThreadId }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 对话页 — 核心交互入口
 * SSE 流式响应 + 思考链可视化 + 会话管理
 */
import { ref, nextTick, watch, onMounted } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useWorkflowStore } from '@/stores/workflow'
import MessageBubble from './components/MessageBubble.vue'
import ThreadSidebar from './components/ThreadSidebar.vue'
import QuickActions from './components/QuickActions.vue'

const chatStore = useChatStore()
const workflowStore = useWorkflowStore()

const inputText = ref('')
const sidebarVisible = ref(false)
const messageContainer = ref<HTMLElement | null>(null)

/** 发送消息 */
function handleSend() {
  const text = inputText.value.trim()
  if (!text || chatStore.isStreaming) return
  inputText.value = ''
  workflowStore.resetExecution()
  chatStore.sendMessage(text)
}

/** 快捷指令 */
function handleQuickAction(text: string) {
  inputText.value = text
  handleSend()
}

/** 消息内快捷回复 */
function handleQuickReply(text: string) {
  inputText.value = text
}

/** 切换会话 */
function handleThreadSelect(threadId: string) {
  chatStore.switchThread(threadId)
  sidebarVisible.value = false
}

/** 新建会话 */
function handleNewThread() {
  chatStore.newThread()
  sidebarVisible.value = false
}

function onScroll() {
  // 滚动行为预留
}

/** 新消息自动滚动到底部 */
watch(
  () => chatStore.messages.length,
  () => {
    nextTick(() => scrollToBottom())
  },
)

watch(
  () => chatStore.lastAssistantMessage?.content,
  () => {
    nextTick(() => scrollToBottom())
  },
)

function scrollToBottom() {
  if (messageContainer.value) {
    messageContainer.value.scrollTop = messageContainer.value.scrollHeight
  }
}

onMounted(() => {
  workflowStore.bindGraphEvents()
})
</script>

<style scoped lang="scss">
.chat-view {
  display: flex;
  height: 100%;
  overflow: hidden;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.message-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px 20px;
  scroll-behavior: smooth;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  animation: fade-in 0.5s ease;

  .empty-icon {
    width: 80px;
    height: 80px;
    margin-bottom: 8px;

    svg {
      width: 100%;
      height: 100%;
    }
  }

  h3 {
    font-size: 20px;
    font-weight: 600;
    color: var(--fa-text-primary);
  }

  p {
    max-width: 420px;
    text-align: center;
    line-height: 1.6;
  }
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.streaming-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 20px;
  font-size: 13px;

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--fa-accent);
    animation: bounce 1.2s infinite ease-in-out;

    &:nth-child(2) { animation-delay: 0.15s; }
    &:nth-child(3) { animation-delay: 0.3s; }
  }
}

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.input-area {
  padding: 12px 20px 16px;
  border-top: 1px solid var(--fa-border-color);
  background: var(--fa-bg-secondary);

  .input-wrapper {
    display: flex;
    align-items: flex-end;
    gap: 10px;
    max-width: 900px;
    margin: 0 auto;

    .sidebar-toggle {
      flex-shrink: 0;
      margin-bottom: 4px;
    }

    :deep(.el-textarea__inner) {
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 14px;
      line-height: 1.5;
      box-shadow: none;
      transition: border-color 0.2s, box-shadow 0.2s;

      &:focus {
        box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.15);
      }
    }

    .send-btn {
      flex-shrink: 0;
      width: 40px;
      height: 40px;
      transition: transform 0.15s;

      &:hover:not(:disabled) {
        transform: scale(1.08);
      }

      &:active:not(:disabled) {
        transform: scale(0.95);
      }
    }
  }

  .input-hint {
    max-width: 900px;
    margin: 6px auto 0;
    font-size: 11px;
    text-align: right;
  }
}
</style>
