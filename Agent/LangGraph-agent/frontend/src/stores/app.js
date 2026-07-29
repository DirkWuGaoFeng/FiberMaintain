import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const agentStatus = ref('online')
  const backendStatus = ref('online')
  const wsStatus = ref('disconnected')
  const currentModel = ref('qwen2.5:7b')

  return { agentStatus, backendStatus, wsStatus, currentModel }
})
