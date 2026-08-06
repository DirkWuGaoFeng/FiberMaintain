/**
 * 图结构 API — /api/v1/graph/*
 */
import { agentClient } from './client'
import type { GraphStructure } from '@/types/graph'

/** 获取主图结构（节点 + 边定义） */
export async function getGraphStructure(): Promise<GraphStructure> {
  const { data } = await agentClient.get<GraphStructure>('/api/v1/graph/structure')
  return data
}
