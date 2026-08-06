/**
 * Workflow Store 单元测试
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useWorkflowStore } from '@/stores/workflow'

// Mock graph API（测试静态兜底逻辑）
vi.mock('@/api/graph', () => ({
  getGraphStructure: vi.fn(() => Promise.reject(new Error('network error'))),
}))

describe('useWorkflowStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('初始状态：无结构 / 无执行记录', () => {
    const store = useWorkflowStore()
    expect(store.structure).toBeNull()
    expect(store.executions).toHaveLength(0)
    expect(store.isExecuting).toBe(false)
  })

  it('loadStructure API 失败时使用静态图结构兜底', async () => {
    const store = useWorkflowStore()
    await store.loadStructure()

    expect(store.structure).not.toBeNull()
    expect(store.structure!.nodes.length).toBe(19)
    expect(store.structure!.edges.length).toBeGreaterThan(25)

    // 验证关键节点存在
    const nodeIds = store.structure!.nodes.map((n) => n.id)
    expect(nodeIds).toContain('input_guard')
    expect(nodeIds).toContain('rule_engine')
    expect(nodeIds).toContain('data_collector')
    expect(nodeIds).toContain('analysis_expert')
    expect(nodeIds).toContain('result_aggregator')
  })

  it('markNodeRunning 记录执行开始', () => {
    const store = useWorkflowStore()
    store.markNodeRunning('input_guard')

    expect(store.nodeStatuses['input_guard']).toBe('running')
    expect(store.executions).toHaveLength(1)
    expect(store.executions[0].nodeId).toBe('input_guard')
    expect(store.executions[0].status).toBe('running')
    expect(store.isExecuting).toBe(true)
  })

  it('markNodeCompleted 记录执行结束和耗时', () => {
    const store = useWorkflowStore()
    store.markNodeRunning('rule_engine')
    store.markNodeCompleted('rule_engine')

    expect(store.nodeStatuses['rule_engine']).toBe('completed')
    expect(store.executions[0].status).toBe('completed')
    expect(store.executions[0].durationMs).toBeGreaterThanOrEqual(0)
    expect(store.isExecuting).toBe(false)
  })

  it('markNodeFailed 标记失败', () => {
    const store = useWorkflowStore()
    store.markNodeRunning('data_collector')
    store.markNodeFailed('data_collector')

    expect(store.nodeStatuses['data_collector']).toBe('failed')
    expect(store.executions[0].status).toBe('failed')
  })

  it('completedCount 统计已完成节点数', () => {
    const store = useWorkflowStore()
    store.markNodeRunning('input_guard')
    store.markNodeCompleted('input_guard')
    store.markNodeRunning('rule_engine')
    store.markNodeCompleted('rule_engine')

    expect(store.completedCount).toBe(2)
  })

  it('updateLoopState 部分更新循环状态', () => {
    const store = useWorkflowStore()
    store.updateLoopState({ loopCount: 2, circuitBreakerOpen: true })

    expect(store.loopState.loopCount).toBe(2)
    expect(store.loopState.circuitBreakerOpen).toBe(true)
    expect(store.loopState.maxLoops).toBe(3) // 未更新字段保持默认
  })

  it('resetExecution 清空全部执行状态', () => {
    const store = useWorkflowStore()
    store.markNodeRunning('input_guard')
    store.markNodeCompleted('input_guard')
    store.updateLoopState({ loopCount: 1 })
    store.resetExecution()

    expect(store.nodeStatuses).toEqual({})
    expect(store.executions).toHaveLength(0)
    expect(store.loopState.loopCount).toBe(0)
  })

  it('bindGraphEvents 监听 CustomEvent 更新节点状态', () => {
    const store = useWorkflowStore()
    store.bindGraphEvents()

    window.dispatchEvent(new CustomEvent('graph:node-start', { detail: { nodeId: 'narrator' } }))
    expect(store.nodeStatuses['narrator']).toBe('running')

    window.dispatchEvent(new CustomEvent('graph:node-end', { detail: { nodeId: 'narrator' } }))
    expect(store.nodeStatuses['narrator']).toBe('completed')
  })
})
