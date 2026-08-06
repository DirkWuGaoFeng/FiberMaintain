/**
 * 系统 API — 健康检查 / 指标 / 降级状态 / 规则热重载
 */
import { agentClient } from './client'
import { silentConfig } from './client'
import type { DegradationStatus, HealthResponse, MetricsSummary } from '@/types/metrics'

/** 健康检查（多组件） */
export async function getHealth(): Promise<HealthResponse> {
  const { data } = await agentClient.get<HealthResponse>('/health', silentConfig())
  return data
}

/** 获取结构化指标摘要 */
export async function getMetricsSummary(): Promise<MetricsSummary> {
  const { data } = await agentClient.get<MetricsSummary>('/api/v1/metrics/summary', silentConfig())
  return data
}

/** 获取降级状态 */
export async function getDegradationStatus(): Promise<DegradationStatus> {
  const { data } = await agentClient.get<DegradationStatus>('/api/v1/degradation', silentConfig())
  return data
}

/** 规则引擎热重载 */
export async function reloadRules(): Promise<{ status: string; rules_loaded: number }> {
  const { data } = await agentClient.post<{ status: string; rules_loaded: number }>('/api/v1/rules/reload')
  return data
}
