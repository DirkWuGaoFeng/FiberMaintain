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

/** 经验整合报告（书籍 Ch3 离线整理阶段） */
export interface ConsolidationReport {
  scanned: number
  merged: number
  merged_disks: number
  hidden_duplicates: number
  marked_stale: number
  by_fiber: Record<string, number>
}

/** 触发经验整合（去重合并/标记过期/超量淘汰） */
export async function consolidateMemory(params?: {
  dry_run?: boolean
  stale_days?: number
  max_per_fiber?: number
}): Promise<{ dry_run: boolean; report: ConsolidationReport }> {
  const { data } = await agentClient.post<{ dry_run: boolean; report: ConsolidationReport }>(
    '/api/v1/memory/consolidate',
    {
      dry_run: params?.dry_run ?? false,
      stale_days: params?.stale_days ?? 180,
      max_per_fiber: params?.max_per_fiber ?? 20,
    },
  )
  return data
}

/** 会话后记忆提取结果（书籍 Ch3 extract→verify→dedupe→store 生命周期） */
export interface ExtractMemoryResult {
  extracted: number
  verified: number
  stored_prefs: number
  stored_events: number
  backfilled_embeddings: number
}

/** 触发会话后记忆提取（后台作业：从对话提取用户偏好/fact/activity 入库） */
export async function extractMemory(params: {
  userId: string
  conversation: string
  maxCandidates?: number
}): Promise<{ user_id: string; result: ExtractMemoryResult }> {
  const { data } = await agentClient.post<{ user_id: string; result: ExtractMemoryResult }>(
    '/api/v1/memory/extract',
    {
      user_id: params.userId,
      conversation: params.conversation,
      max_candidates: params.maxCandidates ?? 5,
    },
  )
  return data
}
