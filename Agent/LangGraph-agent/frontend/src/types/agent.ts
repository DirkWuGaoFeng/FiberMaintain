/**
 * Agent 交互类型定义
 * 对应 LangServe /fiber-agent/* 接口和 MainGraphState
 */

/** 意图分类结果 */
export type IntentType =
  | 'single_query'
  | 'batch_query'
  | 'spanloss_analysis'
  | 'color_diagnosis'
  | 'trend_analysis'
  | 'health_check'
  | 'report_generation'
  | 'knowledge_qa'
  | 'chitchat'

/** 严重度等级 */
export type Severity = 'NORMAL' | 'WARNING' | 'CRITICAL'

/** 处理路径 */
export type ProcessingPath = 'fast' | 'normal' | 'heavy' | 'degraded' | 'blocked'

/** 意图识别结果 */
export interface IntentResult {
  intent: IntentType
  confidence: number
  fiberIds: string[]
  boardIds: string[]
  portIds: string[]
  neId?: string
  color?: string
  timeRange?: string
}

/** 分析结论（AnalysisVerdict） */
export interface AnalysisVerdict {
  conclusion: string
  severity: Severity
  evidence: string[]
  confidence: number
  needMoreData: boolean
  additionalQuery?: {
    reason: string
    tool: string
    params: Record<string, unknown>
  }
}

/** 规则判定结果（RuleJudgment） */
export interface RuleJudgment {
  status: Severity
  findings: string[]
  metrics: Record<string, unknown>
  suggestedActions: string[]
}

/** 循环记录 */
export interface LoopRecord {
  loopNumber: number
  reason: string
  toolRequested: string
  timestamp: string
}

/** 工具调用记录 */
export interface ToolCallRecord {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
  status: 'running' | 'success' | 'error'
  startTime: number
  endTime?: number
}

/** 思考步骤 */
export interface ThinkingStep {
  type: 'intent' | 'rule_judgment' | 'analysis' | 'loop' | 'routing' | 'validation'
  title: string
  content: string
  timestamp: number
  data?: IntentResult | AnalysisVerdict | RuleJudgment | LoopRecord | Record<string, unknown>
}

/** 同步调用请求 */
export interface InvokeRequest {
  message: string
  thread_id?: string
}

/** 同步调用响应 */
export interface InvokeResponse {
  result: string
  processing_path: ProcessingPath
  latency_ms: number
  request_id: string
}

/** SSE 流事件处理器 */
export interface StreamHandlers {
  onNodeStart?: (nodeId: string, data: Record<string, unknown>) => void
  onNodeEnd?: (nodeId: string, data: Record<string, unknown>) => void
  onToken?: (token: string) => void
  onToolStart?: (call: ToolCallRecord) => void
  onToolEnd?: (call: ToolCallRecord) => void
  onThinking?: (step: ThinkingStep) => void
  onClarification?: (message: string) => void
  onComplete?: (finalOutput: string) => void
  onError?: (error: Error) => void
  /** 心跳事件（后端每 5s 发送，表示仍在处理中） */
  onHeartbeat?: (elapsedMs: number) => void
  /** 最终输出事件（快速路径/模板兖底时无 token 流，通过此事件传递结果） */
  onFinalOutput?: (output: string) => void
  /** 记忆事件注入（result_aggregator 按当前问题召回的用户历史事件）[v2.1] */
  onMemoryEvents?: (events: MemoryEvent[]) => void
}

/** 用户历史记忆事件（result_aggregator user_preferences.memory_events）[v2.1] */
export interface MemoryEvent {
  event_type: string
  details: {
    key?: string
    value?: string
    source?: string
    confidence?: number
  }
  similarity?: number
}

/** 批量进度 */
export interface BatchProgress {
  status: 'not_found' | 'running' | 'completed' | 'failed'
  total?: number
  completed?: number
  failed?: number
  results?: unknown[]
}
