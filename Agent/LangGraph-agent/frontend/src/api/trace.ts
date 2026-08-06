/**
 * Trace Diagnostics API — 全链路跟踪查询接口 [v7.2]
 *
 * 对接后端 /api/v1/traces 端点，提供请求链路跟踪数据查询。
 */
import { agentClient } from './client'

/** 跟踪摘要（列表项） */
export interface TraceSummary {
  trace_id: string
  user_input: string
  processing_path: string
  total_ms: number
  status: 'SUCCESS' | 'ERROR' | 'SLOW' | 'TIMEOUT'
  slow_spans: { node: string; duration_ms: number }[]
  timestamp: string
}

/** 单个 Span 详情 */
export interface TraceSpanDetail {
  span_id: string
  node_name: string
  start_time: number
  end_time: number | null
  duration_ms: number | null
  input_summary: string
  output_summary: string
  error: string | null
  metadata: Record<string, unknown>
  is_slow: boolean
  children?: TraceSpanDetail[]
}

/** 完整跟踪详情 */
export interface TraceDetail {
  trace_id: string
  user_input: string
  processing_path: string
  total_ms: number
  span_count: number
  status: string
  slow_spans: { node: string; duration_ms: number }[]
  phase_breakdown: {
    node: string
    duration_ms: number
    percentage: number
    is_slow: boolean
  }[]
  final_output: string
  spans: TraceSpanDetail[]
  timestamp: string
}

/**
 * 获取最近的跟踪记录列表
 */
export async function fetchRecentTraces(limit = 20): Promise<TraceSummary[]> {
  const resp = await agentClient.get('/api/v1/traces', { params: { limit } })
  return resp.data?.traces ?? []
}

/**
 * 获取单条跟踪的完整详情
 */
export async function fetchTraceDetail(traceId: string): Promise<TraceDetail | null> {
  try {
    const resp = await agentClient.get(`/api/v1/traces/${traceId}`)
    return resp.data
  } catch {
    return null
  }
}
