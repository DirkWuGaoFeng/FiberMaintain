/**
 * 工作流状态管理 — 图结构 / 节点实时状态 / 执行追踪
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getGraphStructure } from '@/api/graph'
import type { GraphStructure, NodeExecution, NodeStatus, LoopControlState } from '@/types/graph'

export const useWorkflowStore = defineStore('workflow', () => {
  // ===== 图结构 =====
  const structure = ref<GraphStructure | null>(null)
  const structureLoading = ref(false)

  // ===== 节点实时状态 =====
  const nodeStatuses = ref<Record<string, NodeStatus>>({})
  const executions = ref<NodeExecution[]>([])
  const loopState = ref<LoopControlState>({
    loopCount: 0,
    maxLoops: 3,
    llmCallCount: 0,
    maxLlmCalls: 10,
    noProgressCount: 0,
    maxNoProgress: 2,
    circuitBreakerOpen: false,
  })

  const isExecuting = computed(() => Object.values(nodeStatuses.value).some((s) => s === 'running'))
  const completedCount = computed(() => Object.values(nodeStatuses.value).filter((s) => s === 'completed').length)

  /** 加载图结构 */
  async function loadStructure() {
    if (structure.value) return
    structureLoading.value = true
    try {
      structure.value = await getGraphStructure()
    } catch {
      // 后端不可用时使用静态图结构（与 main_graph.py 18 节点一致）
      structure.value = getStaticStructure()
    } finally {
      structureLoading.value = false
    }
  }

  /** 节点开始执行 */
  function markNodeRunning(nodeId: string) {
    nodeStatuses.value[nodeId] = 'running'
    executions.value.push({
      nodeId,
      status: 'running',
      startTime: Date.now(),
    })
  }

  /** 节点执行完成 */
  function markNodeCompleted(nodeId: string) {
    nodeStatuses.value[nodeId] = 'completed'
    const exec = [...executions.value].reverse().find((e) => e.nodeId === nodeId && e.status === 'running')
    if (exec) {
      exec.status = 'completed'
      exec.endTime = Date.now()
      exec.durationMs = exec.endTime - exec.startTime
    }
  }

  /** 节点执行失败 */
  function markNodeFailed(nodeId: string) {
    nodeStatuses.value[nodeId] = 'failed'
    const exec = [...executions.value].reverse().find((e) => e.nodeId === nodeId && e.status === 'running')
    if (exec) {
      exec.status = 'failed'
      exec.endTime = Date.now()
      exec.durationMs = exec.endTime - exec.startTime
    }
  }

  /** 更新循环控制状态 */
  function updateLoopState(partial: Partial<LoopControlState>) {
    loopState.value = { ...loopState.value, ...partial }
  }

  /** 重置执行状态（新对话开始时） */
  function resetExecution() {
    nodeStatuses.value = {}
    executions.value = []
    loopState.value = {
      loopCount: 0,
      maxLoops: 3,
      llmCallCount: 0,
      maxLlmCalls: 10,
      noProgressCount: 0,
      maxNoProgress: 2,
      circuitBreakerOpen: false,
    }
  }

  /** 监听 chat store 派发的图事件 */
  function bindGraphEvents() {
    window.addEventListener('graph:node-start', ((e: CustomEvent) => {
      markNodeRunning(e.detail.nodeId)
    }) as EventListener)

    window.addEventListener('graph:node-end', ((e: CustomEvent) => {
      markNodeCompleted(e.detail.nodeId)
    }) as EventListener)
  }

  return {
    structure,
    structureLoading,
    nodeStatuses,
    executions,
    loopState,
    isExecuting,
    completedCount,
    loadStructure,
    markNodeRunning,
    markNodeCompleted,
    markNodeFailed,
    updateLoopState,
    resetExecution,
    bindGraphEvents,
  }
})

/**
 * 静态图结构 — 与 src/graph/main_graph.py 18 节点完全一致
 * 后端 /api/v1/graph/structure 不可用时的兜底
 */
function getStaticStructure(): GraphStructure {
  return {
    nodes: [
      { id: 'input_guard', label: '输入防护', type: 'guard', description: '输入长度/注入检测' },
      { id: 'rule_engine', label: '规则引擎', type: 'router', description: 'L0 规则匹配，三路分发' },
      { id: 'fast_path_executor', label: '快速路径', type: 'executor', description: '规则命中直接执行 (<1s)' },
      { id: 'intent_classifier', label: '意图分类', type: 'router', description: 'LLM 14b 意图识别' },
      { id: 'param_gate', label: '参数门控', type: 'guard', description: '强类型参数校验' },
      { id: 'clarification', label: '参数澄清', type: 'executor', description: 'interrupt() 等待用户补充' },
      { id: 'intent_router', label: '意图路由', type: 'router', description: '按意图分发到子图' },
      { id: 'data_collector', label: '数据收集器', type: 'subgraph', description: 'ReAct Agent + 15 个后端工具' },
      { id: 'rule_judgment', label: '规则判定', type: 'executor', description: '程序化阈值判定（零 LLM）' },
      { id: 'analysis_expert', label: '分析专家', type: 'executor', description: 'LLM 14b 深度分析' },
      { id: 'narrator', label: '叙述生成', type: 'generator', description: 'LLM 7b 生成用户回复' },
      { id: 'narrator_validator', label: '叙述校验', type: 'validator', description: '数据忠实性校验' },
      { id: 'template_fallback', label: '模板兜底', type: 'executor', description: '校验失败时零 LLM 模板输出' },
      { id: 'report_generator', label: '报告生成', type: 'generator', description: 'LLM 14b 生成分析报告' },
      { id: 'report_evaluator', label: '报告评估', type: 'validator', description: 'Reflection 质量评估' },
      { id: 'batch_dispatcher', label: '批量分发', type: 'executor', description: 'Send 分块并行处理' },
      { id: 'knowledge_qa', label: '知识问答', type: 'subgraph', description: 'RAG 检索 + LLM 问答' },
      { id: 'result_aggregator', label: '结果聚合', type: 'aggregator', description: '最终输出聚合' },
      { id: 'degradation_handler', label: '降级处理', type: 'executor', description: '降级模式兜底输出' },
    ],
    edges: [
      { source: '__start__', target: 'input_guard', conditional: false },
      { source: 'input_guard', target: 'rule_engine', conditional: false },
      { source: 'rule_engine', target: 'fast_path_executor', label: 'fast_path', conditional: true },
      { source: 'rule_engine', target: 'param_gate', label: 'rule_hit_complex', conditional: true },
      { source: 'rule_engine', target: 'intent_classifier', label: 'rule_miss', conditional: true },
      { source: 'fast_path_executor', target: 'result_aggregator', conditional: false },
      { source: 'intent_classifier', target: 'param_gate', conditional: false },
      { source: 'param_gate', target: 'clarification', label: 'need_clarification', conditional: true },
      { source: 'param_gate', target: 'intent_router', label: 'params_ok', conditional: true },
      { source: 'clarification', target: 'rule_engine', conditional: false, isLoop: true },
      { source: 'intent_router', target: 'data_collector', label: 'data_query', conditional: true },
      { source: 'intent_router', target: 'batch_dispatcher', label: 'batch_query', conditional: true },
      { source: 'intent_router', target: 'knowledge_qa', label: 'knowledge_qa', conditional: true },
      { source: 'intent_router', target: 'result_aggregator', label: 'chitchat', conditional: true },
      { source: 'data_collector', target: 'rule_judgment', conditional: false },
      { source: 'rule_judgment', target: 'analysis_expert', conditional: false },
      { source: 'analysis_expert', target: 'data_collector', label: 'need_more_data', conditional: true, isLoop: true },
      { source: 'analysis_expert', target: 'report_generator', label: 'generate_report', conditional: true },
      { source: 'analysis_expert', target: 'narrator', label: 'direct_narrate', conditional: true },
      { source: 'analysis_expert', target: 'degradation_handler', label: 'degraded', conditional: true },
      { source: 'narrator', target: 'narrator_validator', conditional: false },
      { source: 'narrator_validator', target: 'result_aggregator', label: 'pass', conditional: true },
      { source: 'narrator_validator', target: 'template_fallback', label: 'fail', conditional: true },
      { source: 'template_fallback', target: 'result_aggregator', conditional: false },
      { source: 'report_generator', target: 'report_evaluator', conditional: false },
      { source: 'report_evaluator', target: 'result_aggregator', label: 'pass', conditional: true },
      { source: 'report_evaluator', target: 'report_generator', label: 'refine', conditional: true, isLoop: true },
      { source: 'batch_dispatcher', target: 'result_aggregator', conditional: false },
      { source: 'knowledge_qa', target: 'result_aggregator', conditional: false },
      { source: 'degradation_handler', target: 'result_aggregator', conditional: false },
      { source: 'result_aggregator', target: '__end__', conditional: false },
    ],
  }
}
