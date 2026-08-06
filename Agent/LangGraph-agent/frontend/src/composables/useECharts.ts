/**
 * useECharts — ECharts 实例生命周期管理（自动 resize / dispose）
 */
import { ref, isRef, onMounted, onUnmounted, watch, type Ref } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import { useAppStore } from '@/stores/app'

export function useECharts(chartRef: Ref<HTMLElement | null>, options?: Ref<EChartsOption> | EChartsOption) {
  const appStore = useAppStore()
  let chart: echarts.ECharts | null = null
  const loading = ref(false)

  function initChart() {
    if (!chartRef.value) return
    chart = echarts.init(chartRef.value, appStore.isDark ? 'dark' : 'light', {
      renderer: 'canvas',
    })
    if (options && !isRef(options)) {
      chart.setOption(options)
    }
  }

  function setOption(opt: EChartsOption, notMerge = false) {
    if (!chart) initChart()
    chart?.setOption(opt, notMerge)
  }

  function showLoading() {
    loading.value = true
    chart?.showLoading('default', { text: '', spinnerRadius: 8 })
  }

  function hideLoading() {
    loading.value = false
    chart?.hideLoading()
  }

  function resize() {
    chart?.resize()
  }

  // 监听主题切换
  watch(
    () => appStore.isDark,
    () => {
      if (chart && chartRef.value) {
        chart.dispose()
        initChart()
        if (options && isRef(options)) {
          chart?.setOption(options.value as EChartsOption)
        }
      }
    },
  )

  // 监听响应式 options
  if (options && isRef(options)) {
    watch(options, (newOpt) => {
      setOption(newOpt as EChartsOption)
    }, { deep: true })
  }

  // ResizeObserver 自适应
  let resizeObserver: ResizeObserver | null = null

  onMounted(() => {
    initChart()
    if (chartRef.value) {
      resizeObserver = new ResizeObserver(() => resize())
      resizeObserver.observe(chartRef.value)
    }
  })

  onUnmounted(() => {
    resizeObserver?.disconnect()
    chart?.dispose()
    chart = null
  })

  return { setOption, showLoading, hideLoading, resize, loading }
}
