<template>
  <router-view />
</template>

<script setup lang="ts">
/**
 * 根组件 — 初始化主题和全局 WebSocket 连接
 */
import { onMounted, onUnmounted } from 'vue'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()

onMounted(() => {
  appStore.initTheme()
  appStore.connectWebSocket()
})

onUnmounted(() => {
  appStore.disconnectWebSocket()
})
</script>
