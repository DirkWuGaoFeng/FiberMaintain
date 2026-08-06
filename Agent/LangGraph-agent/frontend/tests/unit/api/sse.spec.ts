/**
 * SSE 流式客户端单元测试 — Mock fetch 验证事件解析
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { streamInvoke } from '@/api/sse'
import type { StreamHandlers } from '@/types/agent'

/** 构造 SSE 文本流 */
function makeSSEStream(events: Array<{ event: string; data: unknown }>): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  const text = events
    .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
    .join('')

  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text))
      controller.close()
    },
  })
}

function mockFetchWith(events: Array<{ event: string; data: unknown }>) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    body: makeSSEStream(events),
  }) as unknown as typeof fetch
}

describe('streamInvoke (SSE)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('解析 on_chain_start/end 映射到图节点', async () => {
    mockFetchWith([
      { event: 'on_chain_start', data: { event: 'on_chain_start', name: 'input_guard', data: {} } },
      { event: 'on_chain_end', data: { event: 'on_chain_end', name: 'input_guard', data: {} } },
      { event: 'on_chain_start', data: { event: 'on_chain_start', name: 'rule_engine', data: {} } },
      { event: 'on_chain_end', data: { event: 'on_chain_end', name: 'rule_engine', data: {} } },
    ])

    const nodeStarts: string[] = []
    const nodeEnds: string[] = []
    const handlers: StreamHandlers = {
      onNodeStart: (id) => nodeStarts.push(id),
      onNodeEnd: (id) => nodeEnds.push(id),
    }

    streamInvoke('测试', 'thread-1', handlers)
    await vi.waitFor(() => expect(nodeEnds).toHaveLength(2))

    expect(nodeStarts).toEqual(['input_guard', 'rule_engine'])
    expect(nodeEnds).toEqual(['input_guard', 'rule_engine'])
  })

  it('过滤非图节点事件', async () => {
    mockFetchWith([
      { event: 'on_chain_start', data: { event: 'on_chain_start', name: 'RunnableSequence', data: {} } },
      { event: 'on_chain_start', data: { event: 'on_chain_start', name: 'data_collector', data: {} } },
    ])

    const nodeStarts: string[] = []
    let completed = false
    const handlers: StreamHandlers = {
      onNodeStart: (id) => nodeStarts.push(id),
      onComplete: () => { completed = true },
    }

    streamInvoke('测试', 'thread-1', handlers)
    await vi.waitFor(() => expect(completed).toBe(true))

    expect(nodeStarts).toEqual(['data_collector'])
  })

  it('解析 on_chat_model_stream token 流', async () => {
    mockFetchWith([
      { event: 'on_chat_model_stream', data: { event: 'on_chat_model_stream', name: 'ChatOllama', data: { chunk: { content: '光纤' } } } },
      { event: 'on_chat_model_stream', data: { event: 'on_chat_model_stream', name: 'ChatOllama', data: { chunk: { content: ' 3' } } } },
      { event: 'on_chat_model_stream', data: { event: 'on_chat_model_stream', name: 'ChatOllama', data: { chunk: { kwargs: { content: ' 正常' } } } } },
    ])

    const tokens: string[] = []
    let completed = false
    const handlers: StreamHandlers = {
      onToken: (t) => tokens.push(t),
      onComplete: () => { completed = true },
    }

    streamInvoke('测试', 'thread-1', handlers)
    await vi.waitFor(() => expect(completed).toBe(true))

    expect(tokens.join('')).toBe('光纤 3 正常')
  })

  it('解析 on_tool_start/end 工具调用配对', async () => {
    mockFetchWith([
      { event: 'on_tool_start', data: { event: 'on_tool_start', name: 'fiber_spanloss_query', run_id: 'run-123', data: { input: { fiber_id: 3 } } } },
      { event: 'on_tool_end', data: { event: 'on_tool_end', name: 'fiber_spanloss_query', run_id: 'run-123', data: { output: '{"spanloss": 4.2}' } } },
    ])

    const toolStarts: string[] = []
    const toolEnds: Array<{ name: string; status: string; result?: string }> = []
    let completed = false
    const handlers: StreamHandlers = {
      onToolStart: (c) => toolStarts.push(c.name),
      onToolEnd: (c) => toolEnds.push({ name: c.name, status: c.status, result: c.result }),
      onComplete: () => { completed = true },
    }

    streamInvoke('测试', 'thread-1', handlers)
    await vi.waitFor(() => expect(completed).toBe(true))

    expect(toolStarts).toEqual(['fiber_spanloss_query'])
    expect(toolEnds).toHaveLength(1)
    expect(toolEnds[0].status).toBe('success')
    expect(toolEnds[0].result).toContain('4.2')
  })

  it('从 intent_classifier 输出提取思考步骤', async () => {
    mockFetchWith([
      {
        event: 'on_chain_end',
        data: {
          event: 'on_chain_end',
          name: 'intent_classifier',
          data: {
            output: {
              intent_result: { intent: 'single_query', confidence: 0.95, fiber_ids: ['3'], board_ids: [], port_ids: [] },
            },
          },
        },
      },
    ])

    const thinkingSteps: Array<{ type: string; content: string }> = []
    let completed = false
    const handlers: StreamHandlers = {
      onThinking: (s) => thinkingSteps.push({ type: s.type, content: s.content }),
      onComplete: () => { completed = true },
    }

    streamInvoke('测试', 'thread-1', handlers)
    await vi.waitFor(() => expect(completed).toBe(true))

    expect(thinkingSteps).toHaveLength(1)
    expect(thinkingSteps[0].type).toBe('intent')
    expect(thinkingSteps[0].content).toContain('single_query')
    expect(thinkingSteps[0].content).toContain('95%')
  })

  it('HTTP 错误触发 onError', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      body: null,
    }) as unknown as typeof fetch

    let errorMsg = ''
    const handlers: StreamHandlers = {
      onError: (e) => { errorMsg = e.message },
    }

    streamInvoke('测试', 'thread-1', handlers)
    await vi.waitFor(() => expect(errorMsg).toContain('500'))
  })

  it('请求体包含正确的 LangServe 格式', () => {
    mockFetchWith([])
    streamInvoke('查询光纤', 'thread-abc', {})

    expect(global.fetch).toHaveBeenCalledWith(
      '/fiber-agent/stream',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"stream_mode":"events"'),
      }),
    )

    const call = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    const body = JSON.parse(call[1].body)
    expect(body.input.messages[0].content).toBe('查询光纤')
    expect(body.config.configurable.thread_id).toBe('thread-abc')
  })

  it('快速路径: final_output 事件触发 onFinalOutput', async () => {
    mockFetchWith([
      { event: 'on_chain_start', data: { event: 'on_chain_start', name: 'rule_engine', data: {} } },
      { event: 'on_chain_end', data: { event: 'on_chain_end', name: 'fast_path_executor', data: { output: { final_output: '光纤 3 当前衰耗为 4.2 dB' } } } },
      { event: 'message', data: { event: 'final_output', data: { output: '光纤 3 当前衰耗为 4.2 dB' } } },
    ])

    let finalOutput = ''
    let completed = false
    const handlers: StreamHandlers = {
      onFinalOutput: (output) => { finalOutput = output },
      onComplete: () => { completed = true },
    }

    streamInvoke('查询光纤 3 的跨段衰耗', 'thread-1', handlers)
    await vi.waitFor(() => expect(completed).toBe(true))

    expect(finalOutput).toBe('光纤 3 当前衰耗为 4.2 dB')
  })

  it('心跳事件触发 onHeartbeat', async () => {
    mockFetchWith([
      { event: 'message', data: { event: 'heartbeat', data: { elapsed_ms: 5000, status: 'processing' } } },
    ])

    let heartbeatMs = 0
    let completed = false
    const handlers: StreamHandlers = {
      onHeartbeat: (ms) => { heartbeatMs = ms },
      onComplete: () => { completed = true },
    }

    streamInvoke('测试', 'thread-1', handlers)
    await vi.waitFor(() => expect(completed).toBe(true))

    expect(heartbeatMs).toBe(5000)
  })

  it('错误事件触发 onError', async () => {
    mockFetchWith([
      { event: 'message', data: { event: 'error', data: { message: 'Request timeout (60s)', code: 'TIMEOUT' } } },
    ])

    let errorMsg = ''
    let completed = false
    const handlers: StreamHandlers = {
      onError: (e) => { errorMsg = e.message },
      onComplete: () => { completed = true },
    }

    streamInvoke('测试', 'thread-1', handlers)
    await vi.waitFor(() => expect(completed).toBe(true))

    expect(errorMsg).toContain('TIMEOUT')
    expect(errorMsg).toContain('timeout')
  })
})
