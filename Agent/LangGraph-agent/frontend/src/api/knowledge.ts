/**
 * 知识库管理 API — /api/v1/knowledge/*
 */
import { agentClient } from './client'
import type {
  KbDocListResponse,
  KbIndexStats,
  KbReindexResponse,
  KbSearchRequest,
  KbSearchResult,
  KbUploadResponse,
} from '@/types/knowledge'

/** 获取文档列表 */
export async function getKnowledgeDocs(): Promise<KbDocListResponse> {
  const { data } = await agentClient.get<KbDocListResponse>('/api/v1/knowledge/docs')
  return data
}

/** 上传文档（multipart/form-data） */
export async function uploadKnowledgeDoc(file: File): Promise<KbUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await agentClient.post<KbUploadResponse>('/api/v1/knowledge/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
  return data
}

/** 删除文档（同步清理向量索引） */
export async function deleteKnowledgeDoc(name: string): Promise<{ status: string }> {
  const { data } = await agentClient.delete<{ status: string }>(`/api/v1/knowledge/docs/${encodeURIComponent(name)}`)
  return data
}

/** 全量重建索引 */
export async function reindexKnowledge(): Promise<KbReindexResponse> {
  const { data } = await agentClient.post<KbReindexResponse>('/api/v1/knowledge/reindex', {}, { timeout: 300000 })
  return data
}

/** 检索测试 */
export async function searchKnowledge(request: KbSearchRequest): Promise<KbSearchResult[]> {
  const { data } = await agentClient.post<{ results: KbSearchResult[] }>('/api/v1/knowledge/search', request)
  return data.results
}

/** 获取索引统计 */
export async function getKnowledgeStats(): Promise<KbIndexStats> {
  const { data } = await agentClient.get<KbIndexStats>('/api/v1/knowledge/stats')
  return data
}
