/**
 * SSE 流式客户端 — 对接 LangServe /fiber-agent/stream
 *
 * LangServe stream_mode="events" 输出格式:
 *   event: on_chain_start / on_chain_end / on_chat_model_stream / on_tool_start / on_tool_end ...
 *   data: {"event": "...", "name": "...", "data": {...}, "run_id": "...", ...}
 */
import type { StreamHandlers, ToolCallRecord, ThinkingStep } from '@/types/agent'

/** 主图已知的 18 个节点 ID */
const GRAPH_NODES = new Set([
  'input_guard', 'rule_engine', 'fast_path_executor', 'intent_classifier',
  'param_gate', 'clarification', 'intent_router', 'data_collector',
  'rule_judgment', 'analysis_expert', 'narrator', 'narrator_validator',
  'template_fallback', 'report_generator', 'report_evaluator',
  'batch_dispatcher', 'knowledge_qa', 'result_aggregator', 'degradation_handler',
])

/** SSE 事件原始结构（LangServe events 模式） */
interface RawSSEEvent {
  event: string
  name: string
  data: Record<string, unknown>
  run_id?: string
  tags?: string[]
  metadata?: Record<string, unknown>
}

/** SSE 全局超时（毫秒）— 比后端 120s 多 10s 余量（模型冷启动场景） */
const SSE_CLIENT_TIMEOUT_MS = 130_000

/**
 * 发起流式调用并解析 SSE 事件流
 * @returns AbortController 用于取消请求
 */
export function streamInvoke(
  message: string,
  threadId: string,
  handlers: StreamHandlers,
): AbortController {
  const controller = new AbortController()

  // 全局超时保护：防止无限等待
  const timeoutId = setTimeout(() => {
    controller.abort()
    handlers.onError?.(new Error(`请求超时 (${SSE_CLIENT_TIMEOUT_MS / 1000}s)，请重试`))
  }, SSE_CLIENT_TIMEOUT_MS)

  // 收到任何数据时重置超时（心跳也算）
  let lastActivity = Date.now()
  const resetTimeout = () => {
    lastActivity = Date.now()
  }

  const body = {
    input: {
      messages: [{ role: 'user', content: message }],
      thread_id: threadId,
      user_input: message,
    },
    config: { configurable: { thread_id: threadId } },
    stream_mode: 'events',
  }

  fetch('/fiber-agent/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then((response) => {
      if (!response.ok || !response.body) {
        throw new Error(`Agent stream failed: HTTP ${response.status}`)
      }
      return parseSSEStream(response.body, handlers, resetTimeout)
    })
    .catch((err: Error) => {
      if (err.name !== 'AbortError') {
        handlers.onError?.(err)
      }
    })
    .finally(() => {
      clearTimeout(timeoutId)
    })

  return controller
}

/**
 * 解析 SSE ReadableStream，逐事件分发到 handlers
 */
async function parseSSEStream(
  body: ReadableStream<Uint8Array>,
  handlers: StreamHandlers,
  onActivity?: () => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      // 收到数据 → 重置超时计时
      onActivity?.()

      buffer += decoder.decode(value, { stream: true })

      // SSE 事件以双换行分隔（兼容 \r\n\r\n 和 \n\n）
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() ?? ''

      for (const block of blocks) {
        if (!block.trim()) continue
        const event = parseSSEBlock(block)
        if (event) {
          dispatchEvent(event, handlers)
        }
      }
    }

    // 处理残余 buffer
    if (buffer.trim()) {
      const event = parseSSEBlock(buffer)
      if (event) dispatchEvent(event, handlers)
    }

    // 流正常结束 → 完成
    handlers.onComplete?.('')
  } finally {
    reader.releaseLock()
  }
}

/**
 * 解析单个 SSE 块:
 *   event: xxx
 *   data: {...json...}
 */
function parseSSEBlock(block: string): RawSSEEvent | null {
  let eventName = ''
  let dataStr = ''

  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event: ')) {
      eventName = line.slice(7).trim()
    } else if (line.startsWith('data: ')) {
      dataStr += line.slice(6)
    }
  }

  if (!dataStr || dataStr === '[DONE]') return null

  try {
    const parsed = JSON.parse(dataStr)
    return {
      event: parsed.event || eventName,
      name: parsed.name || '',
      data: parsed.data || {},
      run_id: parsed.run_id,
      tags: parsed.tags,
      metadata: parsed.metadata,
    }
  } catch {
    return null
  }
}

/** 工具调用临时存储（按 run_id 关联 start/end） */
const pendingToolCalls = new Map<string, ToolCallRecord>()

/**
 * 事件分发 — 将 LangServe 事件映射到前端处理器
 */
function dispatchEvent(event: RawSSEEvent, handlers: StreamHandlers): void {
  const { event: type, name, data } = event

  switch (type) {
    // ── 心跳事件（后端每 5s 发送） ──
    case 'heartbeat': {
      const elapsed = (data.elapsed_ms as number) ?? 0
      handlers.onHeartbeat?.(elapsed)
      break
    }

    // ── 错误事件（后端超时/异常） ──
    case 'error': {
      const msg = (data.message as string) || 'Unknown server error'
      const code = (data.code as string) || 'INTERNAL_ERROR'
      const traceId = (data.trace_id as string) || ''
      const elapsed = (data.elapsed_ms as number) || 0
      const traceHint = traceId ? ` [trace: ${traceId}]` : ''
      handlers.onError?.(new Error(`[${code}] ${msg} (${elapsed}ms)${traceHint}`))
      break
    }

    // ── 最终输出事件（快速路径/模板兖底时无 token 流） ──
    case 'final_output': {
      const output = (data.output as string) || ''
      if (output) handlers.onFinalOutput?.(output)
      break
    }

    case 'on_chain_start': {
      if (GRAPH_NODES.has(name)) {
        handlers.onNodeStart?.(name, data)

        // clarification 节点启动 → 参数澄清
        if (name === 'clarification') {
          const input = data.input as Record<string, unknown> | undefined
          const msg = (input?.clarification_message as string) || ''
          if (msg) handlers.onClarification?.(msg)
        }
      }
      break
    }

    case 'on_chain_end': {
      if (GRAPH_NODES.has(name)) {
        handlers.onNodeEnd?.(name, data)
        extractThinkingFromNodeOutput(name, data, handlers)
      }
      break
    }

    case 'on_chat_model_stream': {
      // LLM token 流
      const chunk = data.chunk as Record<string, unknown> | undefined
      if (chunk) {
        const content = extractTokenContent(chunk)
        if (content) handlers.onToken?.(content)
      }
      break
    }

    case 'on_tool_start': {
      const record: ToolCallRecord = {
        id: event.run_id || crypto.randomUUID(),
        name,
        args: (data.input as Record<string, unknown>) || {},
        status: 'running',
        startTime: Date.now(),
      }
      pendingToolCalls.set(record.id, record)
      handlers.onToolStart?.(record)
      break
    }

    case 'on_tool_end': {
      const runId = event.run_id || ''
      const record = pendingToolCalls.get(runId)
      if (record) {
        record.status = 'success'
        record.endTime = Date.now()
        record.result = truncate(String(data.output ?? ''), 500)
        pendingToolCalls.delete(runId)
        handlers.onToolEnd?.(record)
      } else {
        handlers.onToolEnd?.({
          id: runId || crypto.randomUUID(),
          name,
          args: {},
          result: truncate(String(data.output ?? ''), 500),
          status: 'success',
          startTime: Date.now(),
          endTime: Date.now(),
        })
      }
      break
    }

    default:
      break
  }
}

/**
 * 从节点输出中提取思考步骤（意图/规则判定/分析结论等）
 */
function extractThinkingFromNodeOutput(nodeId: string, data: Record<string, unknown>, handlers: StreamHandlers): void {
  const output = data.output as Record<string, unknown> | undefined
  if (!output) return

  let step: ThinkingStep | null = null

  switch (nodeId) {
    case 'intent_classifier': {
      const result = output.intent_result as Record<string, unknown> | undefined
      if (result) {
        step = {
          type: 'intent',
          title: '意图识别',
          content: `识别意图: ${result.intent} (置信度: ${((result.confidence as number) * 100).toFixed(0)}%)`,
          timestamp: Date.now(),
          data: {
            intent: result.intent,
            confidence: result.confidence,
            fiberIds: result.fiber_ids || [],
            boardIds: result.board_ids || [],
            portIds: result.port_ids || [],
          },
        }
      }
      break
    }

    case 'rule_judgment': {
      const judgment = output.rule_judgment as Record<string, unknown> | undefined
      if (judgment) {
        step = {
          type: 'rule_judgment',
          title: '规则判定',
          content: `状态: ${judgment.status}`,
          timestamp: Date.now(),
          data: {
            status: judgment.status,
            findings: judgment.findings || [],
            metrics: judgment.metrics || {},
            suggestedActions: judgment.suggested_actions || [],
          },
        }
      }
      break
    }

    case 'analysis_expert': {
      const verdict = output.analysis_verdict as Record<string, unknown> | undefined
      if (verdict) {
        step = {
          type: 'analysis',
          title: '分析结论',
          content: String(verdict.conclusion || ''),
          timestamp: Date.now(),
          data: {
            conclusion: verdict.conclusion,
            severity: verdict.severity,
            evidence: verdict.evidence || [],
            confidence: verdict.confidence,
            needMoreData: verdict.need_more_data,
          },
        }
      }
      break
    }

    case 'rule_engine': {
      const match = output.rule_match as Record<string, unknown> | undefined
      if (match) {
        step = {
          type: 'routing',
          title: '规则引擎命中',
          content: `规则: ${match.rule_id || 'unknown'}`,
          timestamp: Date.now(),
          data: match,
        }
      }
      break
    }

    case 'narrator_validator': {
      const passed = output.narrator_validation_passed as boolean | undefined
      step = {
        type: 'validation',
        title: '叙述校验',
        content: passed === false ? '校验未通过，使用模板兜底' : '校验通过',
        timestamp: Date.now(),
        data: { passed },
      }
      break
    }

    default:
      break
  }

  if (step) handlers.onThinking?.(step)
}

/** 从 LangChain message chunk 中提取 token 文本 */
function extractTokenContent(chunk: Record<string, unknown>): string {
  // AIMessageChunk: { content: "..." } 或 { kwargs: { content: "..." } }
  const content = chunk.content ?? (chunk.kwargs as Record<string, unknown>)?.content
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .map((part) => (typeof part === 'string' ? part : (part as Record<string, unknown>)?.text ?? ''))
      .join('')
  }
  return ''
}

/** 截断过长文本 */
function truncate(text: string, maxLen: number): string {
  return text.length > maxLen ? text.slice(0, maxLen) + '...' : text
}
