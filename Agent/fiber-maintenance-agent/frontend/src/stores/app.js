import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAppStore = defineStore('app', () => {
  // 全局加载状态
  const loading = ref(false)
  
  // 系统健康状态
  const systemStatus = ref({
    backend: 'down',
    offlineMode: false,
    version: '-'
  })

  // 全局消息通知
  const notifications = ref([])

  const isHealthy = computed(() => systemStatus.value.backend === 'up')

  function setSystemStatus(status) {
    systemStatus.value = status
  }

  function addNotification(msg) {
    notifications.value.push({ id: Date.now(), ...msg })
    // 5秒后自动移除
    setTimeout(() => {
      notifications.value = notifications.value.filter(n => n.id !== msg.id)
    }, 5000)
  }

  return { loading, systemStatus, notifications, isHealthy, setSystemStatus, addNotification }
})