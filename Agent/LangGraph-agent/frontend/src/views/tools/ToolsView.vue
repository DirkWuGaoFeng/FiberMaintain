<template>
  <div class="tools-view">
    <!-- 页头 -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">{{ $t('tools.title') }}</h2>
        <span class="page-desc">{{ $t('tools.description') }}</span>
      </div>
    </div>

    <div class="tools-content">
      <!-- 左侧：工具分类列表 -->
      <div class="tool-nav">
        <div
          v-for="group in toolGroups"
          :key="group.key"
          class="nav-group"
          :class="{ active: activeGroup === group.key }"
          @click="activeGroup = group.key"
        >
          <span class="group-icon">{{ group.icon }}</span>
          <span class="group-name">{{ $t(`tools.categories.${group.key}`) }}</span>
          <el-tag size="small" type="info" effect="plain">{{ group.tools.length }}</el-tag>
        </div>

        <div class="agent-hint">
          <el-icon><InfoFilled /></el-icon>
          <span>{{ $t('tools.agentHint') }}</span>
        </div>
      </div>

      <!-- 右侧：工具详情 + 执行台 -->
      <div class="tool-detail">
        <div class="tool-list">
          <div
            v-for="tool in currentGroupTools"
            :key="tool.name"
            class="tool-card"
            :class="{ active: selectedTool?.name === tool.name }"
            @click="selectedTool = tool"
          >
            <code class="tool-name">{{ tool.name }}</code>
            <p class="tool-desc">{{ tool.description }}</p>
            <div class="tool-params-preview">
              <el-tag v-for="p in tool.params" :key="p.name" size="small" :type="p.required ? 'danger' : 'info'" effect="plain">
                {{ p.name }}{{ p.required ? '*' : '' }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- 执行面板 -->
        <div v-if="selectedTool" class="exec-panel">
          <div class="exec-header">
            <code class="exec-tool-name">{{ selectedTool.name }}</code>
            <el-button
              type="primary"
              size="small"
              :loading="executing"
              @click="handleExecute"
            >
              {{ executing ? $t('tools.executing') : $t('tools.execute') }}
            </el-button>
          </div>

          <!-- 参数表单 -->
          <div class="param-form">
            <div v-for="param in selectedTool.params" :key="param.name" class="param-row">
              <label class="param-label">
                {{ param.name }}
                <span v-if="param.required" class="required-mark">*</span>
                <span class="param-type">{{ param.type }}</span>
              </label>
              <el-input
                v-model="paramValues[param.name]"
                :placeholder="param.placeholder"
                size="small"
                clearable
              />
            </div>
          </div>

          <!-- 执行结果 -->
          <div v-if="execResult !== null" class="exec-result">
            <div class="result-header">
              <span class="result-title">{{ $t('tools.result') }}</span>
              <el-radio-group v-model="resultView" size="small">
                <el-radio-button value="table">{{ $t('tools.tableView') }}</el-radio-button>
                <el-radio-button value="json">{{ $t('tools.jsonView') }}</el-radio-button>
              </el-radio-group>
              <el-button size="small" text @click="handleCopyResult">
                <el-icon><CopyDocument /></el-icon>
              </el-button>
            </div>

            <!-- JSON 视图 -->
            <pre v-if="resultView === 'json'" class="result-json"><code>{{ formattedResult }}</code></pre>

            <!-- 表格视图 -->
            <div v-else class="result-table">
              <el-table v-if="tableData.length > 0" :data="tableData" size="small" stripe max-height="240">
                <el-table-column
                  v-for="col in tableColumns"
                  :key="col"
                  :prop="col"
                  :label="col"
                  min-width="100"
                  show-overflow-tooltip
                />
              </el-table>
              <pre v-else class="result-json"><code>{{ formattedResult }}</code></pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 工具操作台 — Agent 23+ 工具文档 + 手动调试执行
 * 直接调用 C++ 后端 REST 接口（与 Agent 工具逻辑一致）
 */
import { ref, computed, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { backendClient } from '@/api/client'

const { t } = useI18n()

interface ToolParam {
  name: string
  type: string
  required: boolean
  placeholder: string
}

interface ToolDef {
  name: string
  description: string
  category: string
  method: 'GET' | 'POST'
  endpoint: string
  params: ToolParam[]
}

interface ToolGroup {
  key: string
  icon: string
  tools: ToolDef[]
}

// ===== 工具定义（与后端 src/tools/ 一一对应） =====
const toolGroups = ref<ToolGroup[]>([
  {
    key: 'topology',
    icon: '🌐',
    tools: [
      { name: 'fiber_connection_query', description: '查询光纤连接关系（板卡/端口/对端）', category: 'topology', method: 'GET', endpoint: '/topology/fibers/{fiber_id}', params: [{ name: 'fiber_id', type: 'int', required: true, placeholder: '如: 3' }] },
      { name: 'fiber_scene_query', description: '查询光纤场景信息', category: 'topology', method: 'GET', endpoint: '/topology/fibers/{fiber_id}/scene', params: [{ name: 'fiber_id', type: 'int', required: true, placeholder: '如: 3' }] },
      { name: 'board_query', description: '查询板卡详情', category: 'topology', method: 'GET', endpoint: '/boards/{board_id}', params: [{ name: 'board_id', type: 'int', required: true, placeholder: '如: 1' }] },
      { name: 'board_fibers_query', description: '查询板卡下所有光纤', category: 'topology', method: 'GET', endpoint: '/boards/{board_id}/fibers', params: [{ name: 'board_id', type: 'int', required: true, placeholder: '如: 10003' }] },
    ],
  },
  {
    key: 'performance',
    icon: '📈',
    tools: [
      { name: 'fiber_performance_query', description: '查询光纤性能（OOP/IOP/OSNR）', category: 'performance', method: 'GET', endpoint: '/fibers/{fiber_id}/performance', params: [{ name: 'fiber_id', type: 'int', required: true, placeholder: '如: 3' }] },
      { name: 'fiber_spanloss_query', description: '查询光纤跨段衰耗 (dB)', category: 'performance', method: 'GET', endpoint: '/fibers/{fiber_id}/spanloss', params: [{ name: 'fiber_id', type: 'int', required: true, placeholder: '如: 3' }] },
      { name: 'fiber_history_performance', description: '查询光纤历史性能数据', category: 'performance', method: 'GET', endpoint: '/fibers/{fiber_id}/performance/history', params: [{ name: 'fiber_id', type: 'int', required: true, placeholder: '如: 3' }, { name: 'hours', type: 'int', required: false, placeholder: '默认 24' }] },
      { name: 'fiber_trend_query', description: '光纤色标统计趋势（全局）', category: 'performance', method: 'GET', endpoint: '/fibers/stats/trend', params: [{ name: 'start_time', type: 'string', required: false, placeholder: '如: 2026-07-01 00:00:00' }, { name: 'end_time', type: 'string', required: false, placeholder: '如: 2026-08-01 00:00:00' }] },
    ],
  },
  {
    key: 'alarm',
    icon: '🚨',
    tools: [
      { name: 'alarm_query', description: '查询当前告警列表（支持板卡/端口过滤）', category: 'alarm', method: 'GET', endpoint: '/alarms/current', params: [{ name: 'board_id', type: 'int', required: false, placeholder: '可选' }, { name: 'port_id', type: 'int', required: false, placeholder: '可选' }] },
    ],
  },
  {
    key: 'colored',
    icon: '🎨',
    tools: [
      { name: 'colored_fibers_query', description: '按颜色查询色标光纤（RED/YELLOW/GREEN）', category: 'colored', method: 'GET', endpoint: '/fibers/colored', params: [{ name: 'color', type: 'string', required: false, placeholder: 'RED/YELLOW/GREEN，默认 RED' }] },
      { name: 'all_colored_fibers_query', description: '查询全部非绿色光纤', category: 'colored', method: 'GET', endpoint: '/fibers/colored/all', params: [] },
    ],
  },
  {
    key: 'stats',
    icon: '📊',
    tools: [
      { name: 'fiber_stats_query', description: '光纤实时统计（总数/色标分布/告警）', category: 'stats', method: 'GET', endpoint: '/fibers/stats/realtime', params: [] },
    ],
  },
  {
    key: 'internal',
    icon: '🔧',
    tools: [
      { name: 'system_health', description: 'Agent 系统健康检查', category: 'internal', method: 'GET', endpoint: '/health', params: [], agentApi: true } as ToolDef & { agentApi?: boolean },
      { name: 'event_query', description: '查询事件队列状态', category: 'internal', method: 'GET', endpoint: '/api/v1/degradation', params: [], agentApi: true } as ToolDef & { agentApi?: boolean },
    ],
  },
])

const activeGroup = ref('topology')
const selectedTool = ref<ToolDef | null>(null)
const paramValues = reactive<Record<string, string>>({})
const executing = ref(false)
const execResult = ref<unknown>(null)
const resultView = ref<'table' | 'json'>('json')

const currentGroupTools = computed(() => {
  const group = toolGroups.value.find((g) => g.key === activeGroup.value)
  return group?.tools || []
})

const formattedResult = computed(() => {
  if (execResult.value === null) return ''
  return JSON.stringify(execResult.value, null, 2)
})

/** 尝试从结果中提取表格数据 */
const tableData = computed<Record<string, unknown>[]>(() => {
  const result = execResult.value
  if (Array.isArray(result)) return result.filter((r) => typeof r === 'object') as Record<string, unknown>[]
  if (result && typeof result === 'object') {
    const obj = result as Record<string, unknown>
    // 查找第一个数组字段
    for (const val of Object.values(obj)) {
      if (Array.isArray(val) && val.length > 0 && typeof val[0] === 'object') {
        return val as Record<string, unknown>[]
      }
    }
  }
  return []
})

const tableColumns = computed(() => {
  if (tableData.value.length === 0) return []
  return Object.keys(tableData.value[0]).slice(0, 8)
})

/** 执行工具（直接调用后端 REST） */
async function handleExecute() {
  if (!selectedTool.value) return
  executing.value = true
  execResult.value = null

  try {
    // 替换路径参数
    let url = selectedTool.value.endpoint
    const queryParams: Record<string, string> = {}

    for (const param of selectedTool.value.params) {
      const value = paramValues[param.name]?.trim()
      if (url.includes(`{${param.name}}`)) {
        if (!value) {
          ElMessage.warning(`${param.name} ${t('tools.required')}`)
          executing.value = false
          return
        }
        url = url.replace(`{${param.name}}`, value)
      } else if (value) {
        queryParams[param.name] = value
      }
    }

    const isAgent = (selectedTool.value as ToolDef & { agentApi?: boolean }).agentApi
    const client = isAgent
      ? (await import('@/api/client')).agentClient
      : backendClient

    const { data } = await client.get(url, { params: queryParams, timeout: 30000 })
    execResult.value = data

    // 自动切换表格视图
    if (tableData.value.length > 0) resultView.value = 'table'
  } catch (e) {
    execResult.value = { error: String(e) }
  } finally {
    executing.value = false
  }
}

async function handleCopyResult() {
  try {
    await navigator.clipboard.writeText(formattedResult.value)
    ElMessage.success(t('common.copied'))
  } catch {
    ElMessage.error(t('common.failed'))
  }
}

// 避免 unused 警告
void t
</script>

<style scoped lang="scss">
.tools-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  padding: 16px 20px;
  gap: 14px;
}

.page-header {
  .header-left {
    display: flex;
    align-items: baseline;
    gap: 14px;

    .page-title {
      margin: 0;
      font-size: 16px;
      font-weight: 700;
      color: var(--fa-text-primary);
    }

    .page-desc {
      font-size: 12px;
      color: var(--fa-text-muted);
    }
  }
}

.tools-content {
  flex: 1;
  display: flex;
  gap: 14px;
  min-height: 0;
}

.tool-nav {
  width: 200px;
  min-width: 200px;
  display: flex;
  flex-direction: column;
  gap: 4px;

  .nav-group {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.15s;
    border: 1px solid transparent;

    &:hover {
      background: rgba(64, 158, 255, 0.05);
    }

    &.active {
      background: rgba(64, 158, 255, 0.08);
      border-color: rgba(64, 158, 255, 0.25);
    }

    .group-icon {
      font-size: 15px;
    }

    .group-name {
      flex: 1;
      font-size: 12px;
      font-weight: 600;
      color: var(--fa-text-primary);
    }
  }

  .agent-hint {
    margin-top: auto;
    display: flex;
    gap: 6px;
    align-items: flex-start;
    padding: 10px;
    border-radius: 8px;
    background: var(--fa-bg-tertiary);
    font-size: 10px;
    color: var(--fa-text-muted);
    line-height: 1.5;

    .el-icon {
      flex-shrink: 0;
      margin-top: 1px;
    }
  }
}

.tool-detail {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  overflow-y: auto;

  .tool-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 10px;

    .tool-card {
      padding: 12px;
      border: 1px solid var(--fa-border-color);
      border-radius: 8px;
      background: var(--fa-bg-secondary);
      cursor: pointer;
      transition: border-color 0.2s, transform 0.15s;

      &:hover {
        transform: translateY(-1px);
        border-color: rgba(64, 158, 255, 0.4);
      }

      &.active {
        border-color: var(--fa-accent);
        box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.12);
      }

      .tool-name {
        font-size: 12px;
        font-weight: 700;
        color: var(--fa-accent);
      }

      .tool-desc {
        font-size: 11px;
        color: var(--fa-text-secondary);
        margin: 4px 0 8px;
        line-height: 1.4;
      }

      .tool-params-preview {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
      }
    }
  }

  .exec-panel {
    border: 1px solid var(--fa-border-color);
    border-radius: 10px;
    background: var(--fa-bg-secondary);
    padding: 14px;

    .exec-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;

      .exec-tool-name {
        font-size: 13px;
        font-weight: 700;
        color: var(--fa-text-primary);
      }
    }

    .param-form {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 12px;

      .param-row {
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-width: 160px;
        flex: 1;
        max-width: 240px;

        .param-label {
          font-size: 11px;
          font-weight: 600;
          color: var(--fa-text-secondary);

          .required-mark {
            color: var(--fa-danger);
          }

          .param-type {
            margin-left: 6px;
            font-size: 10px;
            color: var(--fa-text-muted);
            font-weight: 400;
          }
        }
      }
    }

    .exec-result {
      border-top: 1px solid var(--fa-border-color);
      padding-top: 12px;

      .result-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 10px;

        .result-title {
          font-size: 12px;
          font-weight: 700;
          color: var(--fa-text-secondary);
        }
      }

      .result-json {
        margin: 0;
        padding: 12px;
        background: var(--fa-bg-tertiary);
        border-radius: 8px;
        max-height: 280px;
        overflow: auto;

        code {
          font-size: 11px;
          line-height: 1.5;
          color: var(--fa-text-secondary);
          white-space: pre-wrap;
          word-break: break-all;
        }
      }
    }
  }
}
</style>
