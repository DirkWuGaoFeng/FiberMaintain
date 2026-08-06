/**
 * 监控指标类型定义
 * 对应后端 GET /api/v1/metrics/summary 和 Prometheus 指标
 */

/** 降级等级 0-4 */
export type DegradationLevel = 0 | 1 | 2 | 3 | 4

/** 组件健康状态 */
export interface ComponentHealth {
  name: string
  status: 'healthy' | 'unhealthy' | 'degraded'
  latencyMs?: number
  detail?: string
}

/** 健康检查响应 */
export interface HealthResponse {
  status: string
  version?: string
  components?: ComponentHealth[]
}

/** 降级状态响应 */
export interface DegradationStatus {
  level: DegradationLevel
  level_name: string
  llm_status: {
    primary: boolean
    secondary: boolean
    tertiary: boolean
  }
  backend_available: boolean
  last_probe_time?: number
  note?: string
}

/** 指标摘要响应（结构化 JSON，由后端从 Prometheus REGISTRY 提取） */
export interface MetricsSummary {
  requestTotal: Record<string, number>
  ruleHitTotal: Record<string, number>
  toolCalls: Record<string, { success: number; error: number }>
  loopIterations: number
  degradationLevel: DegradationLevel
  tokenUsage: Record<string, number>
  narratorValidationFailures: number
  requestDuration: {
    avg: number
    p95: number
    count: number
  }
}

/** 前端指标快照（含时间戳，用于趋势图） */
export interface MetricsSnapshot {
  timestamp: number
  summary: MetricsSummary
}
