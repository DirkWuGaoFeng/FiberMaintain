/**
 * useTheme — 主题切换组合式函数（委托给 app store）
 */
import { computed } from 'vue'
import { useAppStore } from '@/stores/app'

export function useTheme() {
  const appStore = useAppStore()

  const isDark = computed(() => appStore.isDark)

  function toggle() {
    appStore.toggleTheme()
  }

  return { isDark, toggle }
}
