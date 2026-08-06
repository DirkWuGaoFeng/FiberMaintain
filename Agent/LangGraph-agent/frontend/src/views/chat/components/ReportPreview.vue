<template>
  <div class="report-preview">
    <div class="report-header">
      <el-icon color="var(--fa-accent)"><Document /></el-icon>
      <span class="report-title">{{ $t('chat.report') }}</span>
      <div class="export-actions">
        <el-button size="small" type="primary" plain @click="handleExport('markdown')">
          <el-icon><Download /></el-icon> MD
        </el-button>
        <el-button size="small" plain @click="handleExport('txt')">
          <el-icon><Download /></el-icon> TXT
        </el-button>
        <el-tooltip :content="$t('common.copy')" placement="top">
          <el-button size="small" text circle @click="handleCopy">
            <el-icon><CopyDocument /></el-icon>
          </el-button>
        </el-tooltip>
      </div>
    </div>

    <!-- 报告正文预览 -->
    <div class="report-body markdown-body" v-html="renderedContent" />
  </div>
</template>

<script setup lang="ts">
/**
 * 报告预览组件 — 检测 AI 回复中的报告内容并提供导出
 * 当消息包含报告标志（# 标题 + 表格结构）时由 MessageBubble 渲染
 */
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { marked } from 'marked'

const props = defineProps<{
  content: string
}>()

const { t } = useI18n()

const renderedContent = computed(() => {
  return marked.parse(props.content, { breaks: true, gfm: true }) as string
})

/** 导出为文件下载 */
function handleExport(format: 'markdown' | 'txt') {
  const ext = format === 'markdown' ? 'md' : 'txt'
  const mime = format === 'markdown' ? 'text/markdown' : 'text/plain'
  const filename = `fiber-report-${new Date().toISOString().slice(0, 10)}.${ext}`

  const blob = new Blob([props.content], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)

  ElMessage.success(`${t('common.download')}: ${filename}`)
}

/** 复制到剪贴板 */
async function handleCopy() {
  try {
    await navigator.clipboard.writeText(props.content)
    ElMessage.success(t('common.copied'))
  } catch {
    ElMessage.error(t('common.failed'))
  }
}

/** 判断内容是否为报告格式（静态工具方法，供 MessageBubble 调用） */
export function isReportContent(content: string): boolean {
  if (!content) return false
  const hasTitle = /^#\s+.+/m.test(content)
  const hasTable = /\|.+\|/m.test(content)
  const hasSections = (content.match(/^#{1,3}\s/gm) || []).length >= 2
  return hasTitle && (hasTable || hasSections) && content.length > 200
}
</script>

<style scoped lang="scss">
.report-preview {
  border: 1px solid var(--fa-border-color);
  border-radius: 10px;
  overflow: hidden;
  background: var(--fa-bg-tertiary);

  .report-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--fa-border-color);
    background: var(--fa-bg-secondary);

    .report-title {
      font-size: 13px;
      font-weight: 700;
      color: var(--fa-text-primary);
      flex: 1;
    }

    .export-actions {
      display: flex;
      gap: 6px;
      align-items: center;
    }
  }

  .report-body {
    padding: 16px;
    max-height: 400px;
    overflow-y: auto;
    font-size: 13px;
    line-height: 1.7;
  }
}
</style>
