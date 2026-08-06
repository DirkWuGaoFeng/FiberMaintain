/**
 * Agent 调用 API — /invoke 同步接口
 */
import { agentClient } from './client'
import type { InvokeRequest, InvokeResponse } from '@/types/agent'

/** 同步调用 Agent（非流式，用于简单场景或降级模式） */
export async function invokeAgent(message: string, threadId?: string): Promise<InvokeResponse> {
  const payload: InvokeRequest = { message, thread_id: threadId }
  const { data } = await agentClient.post<InvokeResponse>('/invoke', payload)
  return data
}
