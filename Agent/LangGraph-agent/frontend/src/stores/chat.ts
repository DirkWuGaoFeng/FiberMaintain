/**
 * 对话状态管理 — 消息列表 / 流式状态 / 思考链
 */
import { defineStore } from 'pinia'
import { ref, computed, reactive } from 'vue'
import { streamInvoke } from '@/api/sse'
import type { MemoryEvent, StreamHandlers, ThinkingStep, ToolCallRecord } from '@/types/agent'

/** 消息类型 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  /** 思考步骤（仅 assistant） */
  thinkingSteps: ThinkingStep[]
  /** 工具调用记录（仅 assistant） */
  toolCalls: ToolCallRecord[]
  /** 处理路径（仅 assistant） */
  processingPath?: string
  /** 耗时 ms（仅 assistant） */
  latencyMs?: number
  /** 是否为澄清请求 */
  isClarification?: boolean
  /** 流式生成中 */
  streaming?: boolean
  /** 用户历史记忆事件（双层记忆细节层召回）[v2.1] */
  memoryEvents?: MemoryEvent[]
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref(false)
  const currentThreadId = ref(generateThreadId())
  const currentStreamContent = ref('')
  /** 心跳状态：显示"仍在处理中... Xs" */
  const heartbeatElapsedMs = ref(0)

  let abortController: AbortController | null = null
  let safetyTimeoutId: ReturnType<typeof setTimeout> | null = null

  const lastAssistantMessage = computed(() => {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].role === 'assistant') return messages.value[i]
    }
    return null
  })

  /** 发送消息并启动 SSE 流 */
  function sendMessage(content: string) {
    if (!content.trim() || isStreaming.value) return

    // 添加用户消息
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'user',
      content: content.trim(),
      timestamp: Date.now(),
      thinkingSteps: [],
      toolCalls: [],
    })

    // 创建 assistant 占位消息（reactive 确保 SSE handlers 闭包修改能触发 UI 更新）
    const assistantMsg: ChatMessage = reactive({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      thinkingSteps: [],
      toolCalls: [],
      memoryEvents: [],
      streaming: true,
    })
    messages.value.push(assistantMsg)

    isStreaming.value = true
    currentStreamContent.value = ''
    const startTime = Date.now()

    const handlers: StreamHandlers = {
      onToken: (token) => {
        currentStreamContent.value += token
        assistantMsg.content = currentStreamContent.value
      },
      onNodeStart: (nodeId) => {
        // 由 workflow store 处理（通过事件总线或直接导入）
        window.dispatchEvent(new CustomEvent('graph:node-start', { detail: { nodeId } }))
      },
      onNodeEnd: (nodeId) => {
        window.dispatchEvent(new CustomEvent('graph:node-end', { detail: { nodeId } }))
      },
      onToolStart: (call) => {
        assistantMsg.toolCalls.push({ ...call })
      },
      onToolEnd: (call) => {
        const idx = assistantMsg.toolCalls.findIndex((t) => t.id === call.id)
        if (idx >= 0) {
          assistantMsg.toolCalls[idx] = { ...call }
        } else {
          assistantMsg.toolCalls.push({ ...call })
        }
      },
      onThinking: (step) => {
        assistantMsg.thinkingSteps.push(step)
      },
      onClarification: (msg) => {
        assistantMsg.isClarification = true
        if (msg) {
          assistantMsg.content = msg
          currentStreamContent.value = msg
        }
      },
      onHeartbeat: (elapsedMs) => {
        // 更新心跳状态，UI 可显示“仍在处理中... Xs”
        heartbeatElapsedMs.value = elapsedMs
      },
      onFinalOutput: (output) => {
        // 仅在尚无 token 内容时填充（避免覆盖 LLM 流式输出）
        if (!currentStreamContent.value) {
          currentStreamContent.value = output
          assistantMsg.content = output
        }
      },
      onMemoryEvents: (events) => {
        // 记忆事件注入：展示"记住的关于你"（双层记忆细节层召回）
        assistantMsg.memoryEvents = events
      },
      onComplete: () => {
        assistantMsg.streaming = false
        assistantMsg.latencyMs = Date.now() - startTime
        isStreaming.value = false
        heartbeatElapsedMs.value = 0
        abortController = null
        clearSafetyTimeout()
      },
      onError: (error) => {
        assistantMsg.streaming = false
        if (!assistantMsg.content) {
          assistantMsg.content = `⚠️ ${error.message}`
        }
        isStreaming.value = false
        heartbeatElapsedMs.value = 0
        abortController = null
        clearSafetyTimeout()
      },
    }

    abortController = streamInvoke(content.trim(), currentThreadId.value, handlers)

    // 130s 安全超时（比后端多 10s），防止任何情况下无限卡死
    safetyTimeoutId = setTimeout(() => {
      if (isStreaming.value) {
        stopStreaming()
        assistantMsg.content = assistantMsg.content || '⚠️ 请求超时 (130s)，请重试'
        assistantMsg.streaming = false
      }
    }, 130_000)
  }

  /** 停止当前流式生成 */
  function stopStreaming() {
    abortController?.abort()
    abortController = null
    isStreaming.value = false
    heartbeatElapsedMs.value = 0
    clearSafetyTimeout()
    const last = lastAssistantMessage.value
    if (last) last.streaming = false
  }

  /** 清除安全超时定时器 */
  function clearSafetyTimeout() {
    if (safetyTimeoutId) {
      clearTimeout(safetyTimeoutId)
      safetyTimeoutId = null
    }
  }

  /** 新建会话 */
  function newThread() {
    currentThreadId.value = generateThreadId()
    messages.value = []
    currentStreamContent.value = ''
  }

  /** 切换到指定会话 */
  function switchThread(threadId: string) {
    currentThreadId.value = threadId
    messages.value = []
  }

  /** 清空当前会话消息 */
  function clearMessages() {
    messages.value = []
  }

  function generateThreadId(): string {
    return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  }

  return {
    messages,
    isStreaming,
    currentThreadId,
    heartbeatElapsedMs,
    lastAssistantMessage,
    sendMessage,
    stopStreaming,
    newThread,
    switchThread,
    clearMessages,
  }
})
