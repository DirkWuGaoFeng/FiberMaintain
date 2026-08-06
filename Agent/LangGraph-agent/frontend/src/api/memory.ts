/**
 * 记忆管理 API — /api/v1/memory/*
 */
import { agentClient } from './client'

/** 光纤快照记录 */
export interface FiberSnapshot {
  fiber_id: string
  spanloss: number
  color: string
  summary: string
  created_at: string
}

/** 查询光纤快照历史 */
export async function getSnapshots(fiberId: string, days = 30): Promise<FiberSnapshot[]> {
  const { data } = await agentClient.get<{ snapshots: FiberSnapshot[] }>('/api/v1/memory/snapshots', {
    params: { fiber_id: fiberId, days },
  })
  return data.snapshots
}

/** 获取光纤最新快照 */
export async function getLatestSnapshot(fiberId: string): Promise<FiberSnapshot | null> {
  const { data } = await agentClient.get<{ snapshot: FiberSnapshot | null }>(`/api/v1/memory/latest/${fiberId}`)
  return data.snapshot
}

/** 清理过期记忆 */
export async function cleanupMemory(maxAgeDays = 90): Promise<{ deleted: number }> {
  const { data } = await agentClient.post<{ deleted: number }>('/api/v1/memory/cleanup', {
    max_age_days: maxAgeDays,
  })
  return data
}
