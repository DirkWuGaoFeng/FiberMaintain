/**
 * 批量任务 API — /api/batch/*
 */
import { agentClient } from './client'
import { silentConfig } from './client'
import type { BatchProgress } from '@/types/agent'

/** 查询批量任务进度 */
export async function getBatchProgress(threadId: string): Promise<BatchProgress> {
  const { data } = await agentClient.get<BatchProgress>(`/api/batch/${threadId}/progress`, silentConfig())
  return data
}
