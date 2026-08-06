/**
 * 知识库类型定义
 * 对应后端 /api/v1/knowledge/* 接口
 */

/** 知识分类 */
export type KnowledgeCategory =
  | 'device_manual'
  | 'maintenance_guide'
  | 'alarm_guide'
  | 'fault_cases'
  | 'threshold_standard'
  | 'ne_config'
  | 'testing_guide'
  | 'general'

/** 知识库文档 */
export interface KbDocument {
  name: string
  category: KnowledgeCategory
  chunkCount: number
  sizeBytes: number
  updatedAt: string
}

/** 文档列表响应 */
export interface KbDocListResponse {
  documents: KbDocument[]
  total: number
}

/** 检索结果 */
export interface KbSearchResult {
  content: string
  metadata: {
    source: string
    category: KnowledgeCategory
    chunk_index: number
  }
  score: number
}

/** 检索请求 */
export interface KbSearchRequest {
  query: string
  top_k?: number
}

/** 索引统计 */
export interface KbIndexStats {
  totalDocs: number
  totalChunks: number
  categoryDistribution: Record<KnowledgeCategory, number>
  lastIndexedAt: string | null
  engineAvailable: boolean
}

/** 上传响应 */
export interface KbUploadResponse {
  filename: string
  chunks_added: number
  category: KnowledgeCategory
}

/** 重建索引响应 */
export interface KbReindexResponse {
  status: string
  chunks_ingested: number
}
