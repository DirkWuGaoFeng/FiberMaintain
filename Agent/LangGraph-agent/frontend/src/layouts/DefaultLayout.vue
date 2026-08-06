<template>
  <el-container class="app-layout">
    <!-- 侧边导航栏 -->
    <el-aside :width="collapsed ? '64px' : '220px'" class="app-aside">
      <div class="logo-area" @click="collapsed = !collapsed">
        <img src="/favicon.svg" alt="logo" class="logo-icon" />
        <transition name="fade">
          <span v-show="!collapsed" class="logo-text">{{ $t('common.appName') }}</span>
        </transition>
      </div>

      <el-menu
        :default-active="activeRoute"
        :collapse="collapsed"
        router
        class="nav-menu"
        :collapse-transition="false"
      >
        <el-menu-item v-for="item in navItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ $t(item.titleKey) }}</template>
        </el-menu-item>
      </el-menu>

      <!-- 底部状态区 -->
      <div class="aside-footer">
        <div class="ws-status" :class="wsConnected ? 'online' : 'offline'">
          <span class="status-dot" />
          <span v-show="!collapsed" class="status-text">
            {{ wsConnected ? $t('common.connected') : $t('common.disconnected') }}
          </span>
        </div>
        <div v-show="!collapsed" class="version-tag">v7.1.0</div>
      </div>
    </el-aside>

    <!-- 主内容区 -->
    <el-container class="main-container">
      <el-header class="app-header">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="collapsed = !collapsed">
            <Fold v-if="!collapsed" />
            <Expand v-else />
          </el-icon>
          <h2 class="page-title">{{ $t(currentTitleKey) }}</h2>
        </div>
        <div class="header-right">
          <!-- 降级状态徽章 -->
          <el-tooltip :content="degradationLabel" placement="bottom">
            <el-badge :value="'L' + degradationLevel" :type="degradationType" class="degrade-badge">
              <el-icon :size="18"><Odometer /></el-icon>
            </el-badge>
          </el-tooltip>

          <!-- 语言切换 -->
          <el-dropdown trigger="click" @command="handleLocaleChange">
            <el-button text class="header-btn">
              <el-icon><EditPen /></el-icon>
              <span class="btn-label">{{ locale === 'zh-CN' ? '中' : 'EN' }}</span>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="zh-CN" :disabled="locale === 'zh-CN'">中文</el-dropdown-item>
                <el-dropdown-item command="en-US" :disabled="locale === 'en-US'">English</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <!-- 主题切换 -->
          <el-button text class="header-btn" @click="toggleTheme">
            <el-icon><Moon v-if="!isDark" /><Sunny v-else /></el-icon>
          </el-button>
        </div>
      </el-header>

      <el-main class="app-main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
/**
 * 默认布局 — 侧边栏导航 + 顶栏 + 内容区
 * 响应式：移动端自动折叠侧边栏
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useAppStore } from '@/stores/app'
import { useMonitorStore } from '@/stores/monitor'
import { setLocale, type LocaleKey } from '@/i18n'

const route = useRoute()
const { t, locale } = useI18n()
const appStore = useAppStore()
const monitorStore = useMonitorStore()
const { isDark, wsConnected } = storeToRefs(appStore)
const { degradationLevel } = storeToRefs(monitorStore)

const collapsed = ref(window.innerWidth < 768)

const navItems = [
  { path: '/', titleKey: 'nav.chat', icon: 'ChatDotRound' },
  { path: '/workflow', titleKey: 'nav.workflow', icon: 'Share' },
  { path: '/knowledge', titleKey: 'nav.knowledge', icon: 'Collection' },
  { path: '/monitor', titleKey: 'nav.monitor', icon: 'DataLine' },
  { path: '/topology', titleKey: 'nav.topology', icon: 'Connection' },
  { path: '/tools', titleKey: 'nav.tools', icon: 'SetUp' },
  { path: '/memory', titleKey: 'nav.memory', icon: 'Box' },
]

const activeRoute = computed(() => route.path)
const currentTitleKey = computed(() => {
  const item = navItems.find((n) => n.path === route.path)
  return item?.titleKey ?? 'nav.chat'
})

const degradationLabel = computed(() => t(`monitor.levels.${degradationLevel.value}`))
const degradationType = computed(() => {
  const level = degradationLevel.value
  if (level === 0) return 'success'
  if (level === 1) return 'warning'
  return 'danger'
})

function toggleTheme() {
  appStore.toggleTheme()
}

function handleLocaleChange(command: string) {
  setLocale(command as LocaleKey)
}

// 响应式折叠
function onResize() {
  if (window.innerWidth < 768) collapsed.value = true
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  monitorStore.startPolling()
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  monitorStore.stopPolling()
})
</script>

<style scoped lang="scss">
.app-layout {
  height: 100vh;
  overflow: hidden;
}

.app-aside {
  background: var(--fa-bg-secondary);
  border-right: 1px solid var(--fa-border-color);
  display: flex;
  flex-direction: column;
  transition: width 0.25s ease;
  overflow: hidden;

  .logo-area {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 16px;
    cursor: pointer;
    min-height: 56px;

    .logo-icon {
      width: 32px;
      height: 32px;
      flex-shrink: 0;
    }

    .logo-text {
      font-size: 15px;
      font-weight: 700;
      white-space: nowrap;
      color: var(--fa-text-primary);
    }
  }

  .nav-menu {
    flex: 1;
    border-right: none;
    background: transparent;

    .el-menu-item {
      margin: 4px 8px;
      border-radius: 8px;
      height: 44px;
      line-height: 44px;

      &.is-active {
        background: var(--fa-accent-light);
        font-weight: 600;
      }
    }
  }

  .aside-footer {
    padding: 12px 16px;
    border-top: 1px solid var(--fa-border-color);

    .ws-status {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;

      .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
      }

      &.online .status-dot {
        background: var(--fa-success);
        box-shadow: 0 0 6px var(--fa-success);
      }

      &.offline .status-dot {
        background: var(--fa-danger);
      }

      .status-text {
        color: var(--fa-text-muted);
        white-space: nowrap;
      }
    }

    .version-tag {
      margin-top: 6px;
      font-size: 11px;
      color: var(--fa-text-muted);
    }
  }
}

.main-container {
  overflow: hidden;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--fa-border-color);
  background: var(--fa-bg-secondary);
  height: 56px;
  padding: 0 20px;

  .header-left {
    display: flex;
    align-items: center;
    gap: 12px;

    .collapse-btn {
      font-size: 18px;
      cursor: pointer;
      color: var(--fa-text-secondary);
      transition: color 0.2s;

      &:hover {
        color: var(--fa-accent);
      }
    }

    .page-title {
      font-size: 17px;
      font-weight: 600;
      color: var(--fa-text-primary);
    }
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 8px;

    .degrade-badge {
      margin-right: 8px;
      cursor: default;
    }

    .header-btn {
      font-size: 16px;

      .btn-label {
        margin-left: 4px;
        font-size: 13px;
      }
    }
  }
}

.app-main {
  padding: 0;
  overflow-y: auto;
  background: var(--fa-bg-primary);
}
</style>
