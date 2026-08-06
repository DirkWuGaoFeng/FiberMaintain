/**
 * Chat Store 单元测试
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { watch, nextTick } from 'vue'
import { useChatStore } from '@/stores/chat'
import type { StreamHandlers } from '@/types/agent'

// Mock SSE 模块，捕获 handlers 以便测试
let capturedHandlers: StreamHandlers | null = null
vi.mock('@/api/sse', () => ({
  streamInvoke: vi.fn((_msg: string, _thread: string, handlers: StreamHandlers) => {
    capturedHandlers = handlers
    return new AbortController()
  }),
}))

describe('useChatStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('初始状态：空消息列表 + 非流式', () => {
    const store = useChatStore()
    expect(store.messages).toHaveLength(0)
    expect(store.isStreaming).toBe(false)
    expect(store.currentThreadId).toMatch(/^web-/)
  })

  it('sendMessage 添加用户消息和 assistant 占位消息', () => {
    const store = useChatStore()
    store.sendMessage('查询光纤 3 的跨段衰耗')

    expect(store.messages).toHaveLength(2)
    expect(store.messages[0].role).toBe('user')
    expect(store.messages[0].content).toBe('查询光纤 3 的跨段衰耗')
    expect(store.messages[1].role).toBe('assistant')
    expect(store.messages[1].streaming).toBe(true)
    expect(store.isStreaming).toBe(true)
  })

  it('sendMessage 忽略空消息', () => {
    const store = useChatStore()
    store.sendMessage('   ')
    expect(store.messages).toHaveLength(0)
  })

  it('sendMessage 在流式期间忽略新消息', () => {
    const store = useChatStore()
    store.sendMessage('第一条')
    store.sendMessage('第二条')
    // 只有第一次生效（2 条消息：user + assistant）
    expect(store.messages).toHaveLength(2)
  })

  it('stopStreaming 终止流式状态', () => {
    const store = useChatStore()
    store.sendMessage('测试')
    expect(store.isStreaming).toBe(true)

    store.stopStreaming()
    expect(store.isStreaming).toBe(false)
    expect(store.lastAssistantMessage?.streaming).toBe(false)
  })

  it('newThread 重置消息并生成新 thread ID', () => {
    const store = useChatStore()
    const oldId = store.currentThreadId
    store.sendMessage('测试')
    store.newThread()

    expect(store.messages).toHaveLength(0)
    expect(store.currentThreadId).not.toBe(oldId)
    expect(store.currentThreadId).toMatch(/^web-/)
  })

  it('switchThread 切换线程并清空消息', () => {
    const store = useChatStore()
    store.sendMessage('测试')
    store.switchThread('custom-thread-1')

    expect(store.currentThreadId).toBe('custom-thread-1')
    expect(store.messages).toHaveLength(0)
  })

  it('lastAssistantMessage 返回最后一条 assistant 消息', () => {
    const store = useChatStore()
    expect(store.lastAssistantMessage).toBeNull()

    store.sendMessage('hello')
    expect(store.lastAssistantMessage?.role).toBe('assistant')
  })

  it('clearMessages 清空消息', () => {
    const store = useChatStore()
    store.sendMessage('测试')
    store.clearMessages()
    expect(store.messages).toHaveLength(0)
  })

  it('onFinalOutput 填充快速路径结果到 assistant 消息', () => {
    const store = useChatStore()
    store.sendMessage('查询光纤 3 的跨段衰耗')

    // 模拟后端发送 final_output 事件
    expect(capturedHandlers).not.toBeNull()
    capturedHandlers!.onFinalOutput?.('光纤 3 当前衰耗为 4.2 dB（阈值 5.0 dB），✅ 正常。')

    // 验证 assistant 消息内容被填充
    const assistantMsg = store.lastAssistantMessage
    expect(assistantMsg?.content).toBe('光纤 3 当前衰耗为 4.2 dB（阈值 5.0 dB），✅ 正常。')
  })

  it('onFinalOutput 不覆盖已有的 token 流内容', () => {
    const store = useChatStore()
    store.sendMessage('测试')

    // 先模拟 token 流
    capturedHandlers!.onToken?.('光纤 3 ')
    capturedHandlers!.onToken?.('衰耗正常')

    // 再发送 final_output（不应覆盖）
    capturedHandlers!.onFinalOutput?.('这是快速路径结果')

    const assistantMsg = store.lastAssistantMessage
    expect(assistantMsg?.content).toBe('光纤 3 衰耗正常')
  })

  it('onComplete 结束流式状态并记录耗时', () => {
    const store = useChatStore()
    store.sendMessage('测试')
    expect(store.isStreaming).toBe(true)

    capturedHandlers!.onComplete?.('')

    expect(store.isStreaming).toBe(false)
    expect(store.lastAssistantMessage?.streaming).toBe(false)
    expect(store.lastAssistantMessage?.latencyMs).toBeGreaterThanOrEqual(0)
  })

  it('onError 显示错误信息并结束流式', () => {
    const store = useChatStore()
    store.sendMessage('测试')

    capturedHandlers!.onError?.(new Error('[TIMEOUT] Request timeout (60s)'))

    expect(store.isStreaming).toBe(false)
    expect(store.lastAssistantMessage?.content).toContain('TIMEOUT')
  })

  it('onHeartbeat 更新心跳状态', () => {
    const store = useChatStore()
    store.sendMessage('测试')

    capturedHandlers!.onHeartbeat?.(5000)
    expect(store.heartbeatElapsedMs).toBe(5000)

    capturedHandlers!.onComplete?.('')
    expect(store.heartbeatElapsedMs).toBe(0)
  })

  it('onFinalOutput 触发响应式更新（watch 可观测）', async () => {
    const store = useChatStore()
    store.sendMessage('查询光纤 3 的跨段衰耗')

    let observed = ''
    watch(() => store.lastAssistantMessage?.content, (v) => { observed = v ?? '' })

    capturedHandlers!.onFinalOutput?.('光纤 3 衰耗正常')
    await nextTick()

    expect(observed).toBe('光纤 3 衰耗正常')
  })

  it('onToken 触发响应式更新（watch 可观测）', async () => {
    const store = useChatStore()
    store.sendMessage('测试')

    let observed = ''
    watch(() => store.lastAssistantMessage?.content, (v) => { observed = v ?? '' })

    capturedHandlers!.onToken?.('光纤 3 ')
    await nextTick()
    expect(observed).toBe('光纤 3 ')

    capturedHandlers!.onToken?.('状态正常')
    await nextTick()
    expect(observed).toBe('光纤 3 状态正常')
  })
})
