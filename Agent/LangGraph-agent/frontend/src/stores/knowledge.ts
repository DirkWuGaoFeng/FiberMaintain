/**
 * 知识库状态管理 — 文档列表 / 索引统计 / 检索测试
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  getKnowledgeDocs,
  getKnowledgeStats,
  searchKnowledge,
  uploadKnowledgeDoc,
  deleteKnowledgeDoc,
  reindexKnowledge,
} from '@/api/knowledge'
import type { KbDocument, KbIndexStats, KbSearchResult } from '@/types/knowledge'

export const useKnowledgeStore = defineStore('knowledge', () => {
  const documents = ref<KbDocument[]>([])
  const stats = ref<KbIndexStats | null>(null)
  const searchResults = ref<KbSearchResult[]>([])
  const loading = ref(false)
  const searching = ref(false)
  const uploading = ref(false)
  const reindexing = ref(false)

  /** 加载文档列表 + 统计 */
  async function loadAll() {
    loading.value = true
    try {
      const [docRes, statsRes] = await Promise.allSettled([getKnowledgeDocs(), getKnowledgeStats()])
      if (docRes.status === 'fulfilled') documents.value = docRes.value.documents
      if (statsRes.status === 'fulfilled') stats.value = statsRes.value
    } finally {
      loading.value = false
    }
  }

  /** 上传文档 */
  async function upload(file: File) {
    uploading.value = true
    try {
      const result = await uploadKnowledgeDoc(file)
      await loadAll()
      return result
    } finally {
      uploading.value = false
    }
  }

  /** 删除文档 */
  async function remove(name: string) {
    await deleteKnowledgeDoc(name)
    await loadAll()
  }

  /** 重建索引 */
  async function reindex() {
    reindexing.value = true
    try {
      const result = await reindexKnowledge()
      await loadAll()
      return result
    } finally {
      reindexing.value = false
    }
  }

  /** 检索测试 */
  async function search(query: string, topK = 5) {
    searching.value = true
    try {
      searchResults.value = await searchKnowledge({ query, top_k: topK })
      return searchResults.value
    } finally {
      searching.value = false
    }
  }

  function clearSearchResults() {
    searchResults.value = []
  }

  return {
    documents,
    stats,
    searchResults,
    loading,
    searching,
    uploading,
    reindexing,
    loadAll,
    upload,
    remove,
    reindex,
    search,
    clearSearchResults,
  }
})
