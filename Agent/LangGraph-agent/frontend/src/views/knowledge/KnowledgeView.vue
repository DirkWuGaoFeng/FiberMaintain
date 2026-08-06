<template>
  <div class="knowledge-view">
    <!-- 页头 -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">{{ $t('knowledge.title') }}</h2>
        <el-tag
          :type="knowledgeStore.stats?.engineAvailable ? 'success' : 'danger'"
          size="small"
          effect="plain"
        >
          {{ knowledgeStore.stats?.engineAvailable ? $t('knowledge.engineReady') : $t('knowledge.engineUnavailable') }}
        </el-tag>
      </div>
      <div class="header-actions">
        <el-button :loading="knowledgeStore.reindexing" @click="handleReindex">
          <el-icon><Refresh /></el-icon> {{ $t('knowledge.reindex') }}
        </el-button>
        <el-button :loading="knowledgeStore.loading" text circle @click="knowledgeStore.loadAll()">
          <el-icon><RefreshRight /></el-icon>
        </el-button>
      </div>
    </div>

    <div class="kb-content">
      <!-- 左侧：统计 + 文档列表 -->
      <div class="kb-left">
        <!-- 索引统计卡片 -->
        <div class="stats-row">
          <div class="stat-card">
            <span class="stat-value">{{ knowledgeStore.stats?.totalDocs ?? '—' }}</span>
            <span class="stat-label">{{ $t('knowledge.totalDocs') }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-value">{{ knowledgeStore.stats?.totalChunks ?? '—' }}</span>
            <span class="stat-label">{{ $t('knowledge.totalChunks') }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-value">{{ categoryCount }}</span>
            <span class="stat-label">{{ $t('knowledge.categoryDist') }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-value index-time">{{ lastIndexed }}</span>
            <span class="stat-label">{{ $t('monitor.lastUpdated') }}</span>
          </div>
        </div>

        <!-- 上传区域 -->
        <el-upload
          class="upload-zone"
          drag
          :auto-upload="false"
          :show-file-list="false"
          accept=".md,.txt,.pdf,.rst"
          :on-change="handleFileChange"
        >
          <div class="upload-inner">
            <el-icon :size="32" color="var(--fa-accent)"><UploadFilled /></el-icon>
            <div class="upload-text">{{ $t('knowledge.uploadHint') }}</div>
            <div class="upload-formats">{{ $t('knowledge.uploadFormats') }}</div>
          </div>
        </el-upload>

        <!-- 文档列表 -->
        <div class="doc-table-wrapper">
          <el-table
            :data="knowledgeStore.documents"
            v-loading="knowledgeStore.loading"
            size="small"
            stripe
            class="doc-table"
          >
            <el-table-column prop="name" :label="$t('knowledge.fileName')" min-width="180">
              <template #default="{ row }">
                <span class="doc-name">📄 {{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="category" :label="$t('knowledge.category')" width="120">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ $t(`knowledge.categories.${row.category}`) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="chunkCount" :label="$t('knowledge.chunks')" width="80" align="center" />
            <el-table-column :label="'Size'" width="80" align="center">
              <template #default="{ row }">{{ formatSize(row.sizeBytes) }}</template>
            </el-table-column>
            <el-table-column :label="$t('knowledge.updatedAt')" width="140">
              <template #default="{ row }">{{ formatDate(row.updatedAt) }}</template>
            </el-table-column>
            <el-table-column :label="$t('common.actions')" width="70" align="center">
              <template #default="{ row }">
                <el-button type="danger" text size="small" @click="handleDelete(row.name)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <!-- 右侧：检索测试 -->
      <div class="kb-right">
        <div class="search-panel">
          <div class="panel-title">{{ $t('knowledge.searchTest') }}</div>

          <div class="search-input-row">
            <el-input
              v-model="searchQuery"
              :placeholder="$t('knowledge.searchPlaceholder')"
              clearable
              @keydown.enter="handleSearch"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-button
              type="primary"
              :loading="knowledgeStore.searching"
              :disabled="!searchQuery.trim()"
              @click="handleSearch"
            >
              {{ $t('common.search') }}
            </el-button>
          </div>

          <div class="topk-row">
            <span class="topk-label">{{ $t('knowledge.topK') }}: {{ topK }}</span>
            <el-slider v-model="topK" :min="1" :max="10" :step="1" style="flex: 1" />
          </div>

          <!-- 检索结果 -->
          <div class="search-results">
            <div v-if="knowledgeStore.searching" class="searching-state">
              <el-icon class="is-loading" :size="20"><Loading /></el-icon>
            </div>

            <div v-else-if="knowledgeStore.searchResults.length === 0 && hasSearched" class="no-results">
              {{ $t('common.noData') }}
            </div>

            <transition-group name="result-fade" tag="div" class="result-list">
              <div
                v-for="(result, idx) in knowledgeStore.searchResults"
                :key="idx"
                class="result-card"
              >
                <div class="result-header">
                  <el-tag size="small" effect="dark" type="primary">#{{ idx + 1 }}</el-tag>
                  <span class="result-source">{{ result.metadata.source }}</span>
                  <el-tag size="small" effect="plain">
                    {{ $t('knowledge.score') }}: {{ (result.score * 100).toFixed(0) }}%
                  </el-tag>
                </div>
                <p class="result-content">{{ result.content }}</p>
                <div class="result-meta">
                  <el-tag size="small" type="info" effect="plain">
                    {{ $t(`knowledge.categories.${result.metadata.category}`) }}
                  </el-tag>
                  <span class="chunk-idx">chunk #{{ result.metadata.chunk_index }}</span>
                </div>
              </div>
            </transition-group>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 知识库管理页 — 文档管理 + 索引统计 + RAG 检索测试
 */
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useKnowledgeStore } from '@/stores/knowledge'
import type { UploadFile } from 'element-plus'

const { t } = useI18n()
const knowledgeStore = useKnowledgeStore()

const searchQuery = ref('')
const topK = ref(5)
const hasSearched = ref(false)

const categoryCount = computed(() => {
  const dist = knowledgeStore.stats?.categoryDistribution
  return dist ? Object.keys(dist).length : 0
})

const lastIndexed = computed(() => {
  const iso = knowledgeStore.stats?.lastIndexedAt
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
})

async function handleFileChange(uploadFile: UploadFile) {
  if (!uploadFile.raw) return
  try {
    const result = await knowledgeStore.upload(uploadFile.raw)
    ElMessage.success(`${t('common.upload')}: ${result.filename} (+${result.chunks_added} chunks)`)
  } catch (e) {
    ElMessage.error(`${t('common.failed')}: ${e}`)
  }
}

async function handleDelete(name: string) {
  try {
    await ElMessageBox.confirm(
      t('knowledge.deleteDocConfirm', { name }),
      t('knowledge.deleteDoc'),
      { confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel'), type: 'warning' },
    )
    await knowledgeStore.remove(name)
    ElMessage.success(t('common.success'))
  } catch {
    // 取消
  }
}

async function handleReindex() {
  try {
    await ElMessageBox.confirm(
      t('knowledge.reindexConfirm'),
      t('knowledge.reindex'),
      { confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'), type: 'warning' },
    )
    const result = await knowledgeStore.reindex()
    ElMessage.success(t('knowledge.reindexSuccess', { count: result?.chunks_ingested ?? 0 }))
  } catch {
    // 取消
  }
}

async function handleSearch() {
  if (!searchQuery.value.trim()) return
  hasSearched.value = true
  await knowledgeStore.search(searchQuery.value.trim(), topK.value)
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

onMounted(() => {
  knowledgeStore.loadAll()
})
</script>

<style scoped lang="scss">
.knowledge-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  padding: 16px 20px;
  gap: 14px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;

  .header-left {
    display: flex;
    align-items: center;
    gap: 12px;

    .page-title {
      margin: 0;
      font-size: 16px;
      font-weight: 700;
      color: var(--fa-text-primary);
    }
  }

  .header-actions {
    display: flex;
    gap: 8px;
  }
}

.kb-content {
  flex: 1;
  display: flex;
  gap: 16px;
  min-height: 0;
}

.kb-left {
  flex: 1.4;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  overflow-y: auto;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;

  .stat-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 12px 8px;
    border: 1px solid var(--fa-border-color);
    border-radius: 8px;
    background: var(--fa-bg-secondary);
    transition: transform 0.15s, box-shadow 0.15s;

    &:hover {
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
    }

    .stat-value {
      font-size: 20px;
      font-weight: 800;
      color: var(--fa-accent);
      font-family: 'JetBrains Mono', monospace;

      &.index-time {
        font-size: 12px;
        font-weight: 600;
      }
    }

    .stat-label {
      font-size: 11px;
      color: var(--fa-text-muted);
    }
  }
}

.upload-zone {
  :deep(.el-upload-dragger) {
    padding: 16px;
    border-radius: 10px;
    transition: border-color 0.2s, background 0.2s;

    &:hover {
      border-color: var(--fa-accent);
      background: rgba(64, 158, 255, 0.03);
    }
  }

  .upload-inner {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;

    .upload-text {
      font-size: 13px;
      color: var(--fa-text-secondary);
    }

    .upload-formats {
      font-size: 11px;
      color: var(--fa-text-muted);
    }
  }
}

.doc-table-wrapper {
  flex: 1;
  min-height: 0;

  .doc-name {
    font-size: 12px;
    font-weight: 500;
  }
}

.kb-right {
  flex: 1;
  min-width: 320px;
  display: flex;
  flex-direction: column;
}

.search-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--fa-border-color);
  border-radius: 10px;
  background: var(--fa-bg-secondary);
  padding: 14px;
  min-height: 0;

  .panel-title {
    font-size: 13px;
    font-weight: 700;
    color: var(--fa-text-primary);
    margin-bottom: 12px;
  }

  .search-input-row {
    display: flex;
    gap: 8px;
  }

  .topk-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 10px;

    .topk-label {
      font-size: 11px;
      color: var(--fa-text-muted);
      white-space: nowrap;
    }
  }

  .search-results {
    flex: 1;
    margin-top: 14px;
    overflow-y: auto;
    min-height: 0;

    .searching-state, .no-results {
      display: flex;
      justify-content: center;
      padding: 30px 0;
      font-size: 12px;
      color: var(--fa-text-muted);
    }

    .result-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .result-card {
      border: 1px solid var(--fa-border-color);
      border-radius: 8px;
      padding: 10px 12px;
      background: var(--fa-bg-primary);
      transition: border-color 0.2s;

      &:hover {
        border-color: var(--fa-accent);
      }

      .result-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 6px;

        .result-source {
          flex: 1;
          font-size: 11px;
          font-weight: 600;
          color: var(--fa-text-secondary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
      }

      .result-content {
        font-size: 12px;
        color: var(--fa-text-primary);
        line-height: 1.6;
        margin: 0 0 8px;
        display: -webkit-box;
        -webkit-line-clamp: 4;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }

      .result-meta {
        display: flex;
        align-items: center;
        gap: 8px;

        .chunk-idx {
          font-size: 10px;
          color: var(--fa-text-muted);
          font-family: monospace;
        }
      }
    }
  }
}

.result-fade-enter-active {
  transition: all 0.3s ease;
}

.result-fade-enter-from {
  opacity: 0;
  transform: translateY(10px);
}
</style>
