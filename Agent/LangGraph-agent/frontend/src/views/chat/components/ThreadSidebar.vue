<template>
  <transition name="drawer-slide">
    <aside v-show="visible" class="thread-sidebar">
      <div class="sidebar-header">
        <span class="sidebar-title">{{ $t('chat.threadList') }}</span>
        <div class="header-actions">
          <el-tooltip :content="$t('common.refresh')" placement="bottom">
            <el-button text circle size="small" :loading="threadsStore.loading" @click="threadsStore.loadThreads()">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </el-tooltip>
          <el-button text circle size="small" @click="emit('close')">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
      </div>

      <!-- 新建会话按钮 -->
      <div class="new-thread-area">
        <el-button type="primary" class="new-thread-btn" @click="emit('new-thread')">
          <el-icon><Plus /></el-icon>
          {{ $t('chat.newThread') }}
        </el-button>
      </div>

      <!-- 当前会话 -->
      <div class="thread-section">
        <div class="section-label">当前会话</div>
        <div class="thread-item active">
          <el-icon class="thread-icon"><ChatDotRound /></el-icon>
          <div class="thread-info">
            <span class="thread-id">{{ chatStore.currentThreadId }}</span>
            <span class="thread-meta">{{ chatStore.messages.length }} 条消息</span>
          </div>
        </div>
      </div>

      <!-- 历史会话列表 -->
      <div class="thread-section history">
        <div class="section-label">历史会话</div>

        <el-scrollbar class="thread-scroll">
          <div v-if="threadsStore.loading" class="loading-state">
            <el-icon class="is-loading"><Loading /></el-icon>
          </div>

          <div v-else-if="threadsStore.threads.length === 0" class="empty-threads">
            <span class="text-muted">{{ $t('common.noData') }}</span>
          </div>

          <div
            v-for="thread in threadsStore.threads"
            :key="thread.threadId"
            class="thread-item"
            :class="{ active: thread.threadId === chatStore.currentThreadId }"
            @click="emit('select', thread.threadId)"
          >
            <el-icon class="thread-icon"><ChatLineRound /></el-icon>
            <div class="thread-info">
              <span class="thread-preview">{{ thread.preview || thread.threadId }}</span>
              <span class="thread-meta">
                {{ formatTime(thread.lastActiveAt) }}
                <template v-if="thread.messageCount"> · {{ thread.messageCount }} 条</template>
              </span>
            </div>
            <el-button
              class="delete-btn"
              text
              circle
              size="small"
              @click.stop="handleDelete(thread.threadId)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </el-scrollbar>
      </div>
    </aside>
  </transition>
</template>

<script setup lang="ts">
/**
 * 会话线程侧栏 — 线程列表 / 切换 / 新建 / 删除
 */
import { watch } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useThreadsStore } from '@/stores/threads'
import { useChatStore } from '@/stores/chat'

defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  close: []
  select: [threadId: string]
  'new-thread': []
}>()

const { t } = useI18n()
const threadsStore = useThreadsStore()
const chatStore = useChatStore()

/** 侧栏打开时加载线程列表 */
watch(
  () => threadsStore.threads,
  () => { /* reactive trigger */ },
)

watch(
  () => chatStore.currentThreadId,
  () => { /* keep sidebar reactive to thread changes */ },
)

async function handleDelete(threadId: string) {
  try {
    await ElMessageBox.confirm(
      t('chat.deleteThreadConfirm'),
      t('chat.deleteThread'),
      { confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel'), type: 'warning' },
    )
    await threadsStore.removeThread(threadId)
    ElMessage.success(t('common.success'))
  } catch {
    // 用户取消
  }
}

function formatTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  if (diffMs < 60_000) return '刚刚'
  if (diffMs < 3_600_000) return `${Math.floor(diffMs / 60_000)} 分钟前`
  if (diffMs < 86_400_000) return `${Math.floor(diffMs / 3_600_000)} 小时前`
  return d.toLocaleDateString()
}
</script>

<style scoped lang="scss">
.thread-sidebar {
  width: 280px;
  min-width: 280px;
  height: 100%;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--fa-border-color);
  background: var(--fa-bg-secondary);

  .sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 14px 10px;

    .sidebar-title {
      font-size: 14px;
      font-weight: 700;
      color: var(--fa-text-primary);
    }

    .header-actions {
      display: flex;
      gap: 2px;
    }
  }

  .new-thread-area {
    padding: 0 14px 12px;

    .new-thread-btn {
      width: 100%;
      border-radius: 8px;
      font-weight: 600;
    }
  }

  .thread-section {
    padding: 0 10px;

    .section-label {
      font-size: 11px;
      font-weight: 600;
      color: var(--fa-text-muted);
      text-transform: uppercase;
      letter-spacing: 0.8px;
      padding: 6px 6px 4px;
    }

    &.history {
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 0;
      padding-bottom: 12px;

      .thread-scroll {
        flex: 1;
      }
    }
  }

  .thread-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px;
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.15s, transform 0.1s;
    position: relative;

    &:hover {
      background: rgba(64, 158, 255, 0.06);

      .delete-btn {
        opacity: 1;
      }
    }

    &.active {
      background: rgba(64, 158, 255, 0.1);
      border: 1px solid rgba(64, 158, 255, 0.25);
    }

    .thread-icon {
      font-size: 18px;
      color: var(--fa-text-muted);
      flex-shrink: 0;
    }

    .thread-info {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 2px;

      .thread-id, .thread-preview {
        font-size: 12px;
        font-weight: 500;
        color: var(--fa-text-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .thread-id {
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
      }

      .thread-meta {
        font-size: 11px;
        color: var(--fa-text-muted);
      }
    }

    .delete-btn {
      opacity: 0;
      transition: opacity 0.15s;
      color: var(--fa-text-muted);
      flex-shrink: 0;

      &:hover {
        color: var(--fa-danger);
      }
    }
  }

  .loading-state, .empty-threads {
    display: flex;
    justify-content: center;
    padding: 24px 0;
    font-size: 12px;
  }
}

.drawer-slide-enter-active, .drawer-slide-leave-active {
  transition: all 0.25s ease;
}

.drawer-slide-enter-from, .drawer-slide-leave-to {
  transform: translateX(-100%);
  opacity: 0;
  width: 0;
  min-width: 0;
}
</style>
