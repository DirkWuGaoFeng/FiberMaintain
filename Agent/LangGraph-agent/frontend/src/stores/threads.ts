/**
 * 会话线程状态管理 — 线程列表 / 切换 / 删除
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getThreads, deleteThread } from '@/api/threads'
import type { ThreadInfo } from '@/types/graph'

export const useThreadsStore = defineStore('threads', () => {
  const threads = ref<ThreadInfo[]>([])
  const loading = ref(false)

  /** 加载线程列表 */
  async function loadThreads() {
    loading.value = true
    try {
      threads.value = await getThreads()
    } catch {
      // 后端不可用时保持空列表
      threads.value = []
    } finally {
      loading.value = false
    }
  }

  /** 删除线程 */
  async function removeThread(threadId: string) {
    await deleteThread(threadId)
    threads.value = threads.value.filter((t) => t.threadId !== threadId)
  }

  return {
    threads,
    loading,
    loadThreads,
    removeThread,
  }
})
