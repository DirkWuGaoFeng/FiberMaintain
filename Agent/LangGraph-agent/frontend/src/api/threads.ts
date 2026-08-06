/**
 * 会话线程管理 API — /api/v1/threads/*
 */
import { agentClient } from './client'
import type { ThreadInfo, ThreadState } from '@/types/graph'

/** 获取线程列表 */
export async function getThreads(): Promise<ThreadInfo[]> {
  const { data } = await agentClient.get<{ threads: ThreadInfo[] }>('/api/v1/threads')
  return data.threads
}

/** 获取线程状态快照 */
export async function getThreadState(threadId: string): Promise<ThreadState> {
  const { data } = await agentClient.get<ThreadState>(`/api/v1/threads/${threadId}/state`)
  return data
}

/** 删除线程 */
export async function deleteThread(threadId: string): Promise<{ status: string }> {
  const { data } = await agentClient.delete<{ status: string }>(`/api/v1/threads/${threadId}`)
  return data
}

/** 中断线程当前执行 */
export async function interruptThread(threadId: string): Promise<{ status: string }> {
  const { data } = await agentClient.post<{ status: string }>(`/api/v1/threads/${threadId}/interrupt`)
  return data
}
