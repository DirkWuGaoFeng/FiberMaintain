/**
 * usePolling — 通用轮询组合式函数
 */
import { ref, onUnmounted } from 'vue'

export function usePolling(fn: () => Promise<void>, intervalMs = 15000) {
  const active = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  function start() {
    if (active.value) return
    active.value = true
    fn()
    timer = setInterval(fn, intervalMs)
  }

  function stop() {
    active.value = false
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  onUnmounted(stop)

  return { active, start, stop }
}
