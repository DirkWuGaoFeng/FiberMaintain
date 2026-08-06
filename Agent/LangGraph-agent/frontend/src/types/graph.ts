/**
 * 工作流图结构类型定义
 * 对应后端 GET /api/v1/graph/structure 和 LangGraph 状态机
 */

/** 节点类型分类 */
export type NodeType = 'guard' | 'router' | 'executor' | 'subgraph' | 'aggregator' | 'validator' | 'generator'

/** 节点运行状态 */
export type NodeStatus = 'idle' | 'running' | 'completed' | 'failed' | 'skipped'

/** 图节点定义 */
export interface GraphNodeDef {
  id: string
  label: string
  type: NodeType
  description?: string
}

/** 图边定义 */
export interface GraphEdgeDef {
  source: string
  target: string
  label?: string
  conditional: boolean
  isLoop?: boolean
}

/** 图结构响应 */
export interface GraphStructure {
  nodes: GraphNodeDef[]
  edges: GraphEdgeDef[]
}

/** 节点执行记录（用于时间线） */
export interface NodeExecution {
  nodeId: string
  status: NodeStatus
  startTime: number
  endTime?: number
  durationMs?: number
  metadata?: Record<string, unknown>
}

/** 循环控制状态（4 重终止保护） */
export interface LoopControlState {
  loopCount: number
  maxLoops: number
  llmCallCount: number
  maxLlmCalls: number
  noProgressCount: number
  maxNoProgress: number
  circuitBreakerOpen: boolean
}

/** 线程状态快照 */
export interface ThreadState {
  threadId: string
  currentNode: string | null
  intent: string | null
  loopCount: number
  processingPath: string
  degradationLevel: number
  finalOutput: string | null
  createdAt?: string
  lastActiveAt?: string
}

/** 线程列表项 */
export interface ThreadInfo {
  threadId: string
  lastActiveAt: string
  messageCount?: number
  preview?: string
}
