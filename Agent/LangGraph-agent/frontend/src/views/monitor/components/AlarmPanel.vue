<template>
  <div class="alarm-panel">
    <div class="panel-header">
      <span class="panel-title">{{ $t('alarm.title') }}</span>
      <div class="header-actions">
        <span v-if="alarmStore.lastFetchTime" class="fetch-time">
          {{ formatTime(alarmStore.lastFetchTime) }}
        </span>
        <el-button size="small" text :loading="alarmStore.loading" @click="alarmStore.fetchCurrentAlarms()">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- 告警统计卡片 -->
    <div class="alarm-stats-row">
      <div class="stat-chip total">
        <span class="chip-value">{{ alarmStore.summary.total }}</span>
        <span class="chip-label">{{ $t('alarm.total') }}</span>
      </div>
      <div class="stat-chip critical" :class="{ active: alarmStore.summary.critical > 0 }">
        <span class="chip-value">{{ alarmStore.summary.critical }}</span>
        <span class="chip-label">{{ $t('alarm.critical') }}</span>
        <span v-if="alarmStore.summary.critical > 0" class="chip-pulse" />
      </div>
      <div class="stat-chip minor">
        <span class="chip-value">{{ alarmStore.summary.minor }}</span>
        <span class="chip-label">{{ $t('alarm.minor') }}</span>
      </div>
      <div class="stat-chip unspecified">
        <span class="chip-value">{{ alarmStore.summary.unspecified }}</span>
        <span class="chip-label">{{ $t('alarm.unspecified') }}</span>
      </div>
    </div>

    <!-- 最新告警列表 -->
    <div class="alarm-list">
      <div v-if="alarmStore.mergedAlarms.length === 0" class="no-alarms">
        <el-icon :size="20" color="var(--fa-success)"><CircleCheck /></el-icon>
        <span>{{ $t('alarm.noAlarms') }}</span>
      </div>
      <TransitionGroup v-else name="alarm-item" tag="div" class="alarm-items">
        <div
          v-for="(alarm, idx) in displayAlarms"
          :key="`${alarm.alarm_level}-${alarm.raised_at}-${idx}`"
          class="alarm-item"
          :class="levelClass(alarm.alarm_level)"
        >
          <span class="alarm-dot" />
          <div class="alarm-info">
            <span class="alarm-main">
              {{ $t('alarm.boardId') }}: {{ alarm.board_id }}
              <template v-if="alarm.port_id > 0"> / {{ $t('alarm.portId') }}: {{ alarm.port_id }}</template>
            </span>
            <span class="alarm-time">{{ formatTimestamp(alarm.raised_at) }}</span>
          </div>
          <el-tag :type="levelTagType(alarm.alarm_level)" size="small" effect="dark" class="alarm-tag">
            {{ levelLabel(alarm.alarm_level) }}
          </el-tag>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 当前告警状态面板 — 统计卡片 + 最新告警列表
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAlarmStore } from '@/stores/alarm'
import type { AlarmLevel } from '@/types/alarm'

const { t } = useI18n()
const alarmStore = useAlarmStore()

/** 最多显示 8 条告警 */
const displayAlarms = computed(() => alarmStore.mergedAlarms.slice(0, 8))

function levelClass(level: AlarmLevel): string {
  if (level === 'CRITICAL' || level === 'MAJOR') return 'is-critical'
  if (level === 'MINOR') return 'is-minor'
  return 'is-info'
}

function levelTagType(level: AlarmLevel): 'danger' | 'warning' | 'info' {
  if (level === 'CRITICAL' || level === 'MAJOR') return 'danger'
  if (level === 'MINOR') return 'warning'
  return 'info'
}

function levelLabel(level: AlarmLevel): string {
  switch (level) {
    case 'CRITICAL': return t('alarm.critical')
    case 'MAJOR': return t('alarm.critical')
    case 'MINOR': return t('alarm.minor')
    default: return t('alarm.unspecified')
  }
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false })
}

function formatTimestamp(ts: string): string {
  if (!ts) return '--'
  const d = new Date(ts)
  return isNaN(d.getTime()) ? ts : d.toLocaleTimeString('zh-CN', { hour12: false })
}
</script>

<style scoped lang="scss">
.alarm-panel {
  border: 1px solid var(--fa-border-color);
  border-radius: 10px;
  background: var(--fa-bg-secondary);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;

  .panel-title {
    font-size: 13px;
    font-weight: 700;
    color: var(--fa-text-primary);
    letter-spacing: 0.3px;
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 8px;

    .fetch-time {
      font-size: 10px;
      color: var(--fa-text-muted);
      font-family: 'JetBrains Mono', monospace;
    }
  }
}

.alarm-stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 10px;

  .stat-chip {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 10px 8px;
    border-radius: 8px;
    border: 1px solid var(--fa-border-color);
    background: var(--fa-bg-primary);
    overflow: hidden;
    transition: transform 0.15s, box-shadow 0.15s;

    &:hover {
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
    }

    .chip-value {
      font-size: 20px;
      font-weight: 800;
      font-family: 'JetBrains Mono', monospace;
      line-height: 1.2;
    }

    .chip-label {
      font-size: 10px;
      color: var(--fa-text-muted);
      margin-top: 2px;
    }

    .chip-pulse {
      position: absolute;
      top: 6px;
      right: 6px;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--fa-danger);
      animation: chip-blink 1s infinite;
    }

    &.total .chip-value { color: var(--fa-text-primary); }
    &.critical .chip-value { color: var(--fa-danger); }
    &.critical.active { border-color: rgba(245, 108, 108, 0.4); }
    &.minor .chip-value { color: var(--fa-warning); }
    &.unspecified .chip-value { color: var(--fa-text-secondary); }
  }
}

.alarm-list {
  min-height: 60px;

  .no-alarms {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 16px 0;
    font-size: 12px;
    color: var(--fa-text-muted);
  }

  .alarm-items {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-height: 240px;
    overflow-y: auto;
  }

  .alarm-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border-radius: 6px;
    border: 1px solid var(--fa-border-color);
    border-left: 3px solid transparent;
    transition: background 0.15s;

    &:hover { background: var(--fa-bg-primary); }

    .alarm-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      flex-shrink: 0;
    }

    .alarm-info {
      flex: 1;
      display: flex;
      align-items: baseline;
      gap: 10px;
      min-width: 0;

      .alarm-main {
        font-size: 12px;
        font-weight: 500;
        color: var(--fa-text-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .alarm-time {
        font-size: 10px;
        color: var(--fa-text-muted);
        font-family: 'JetBrains Mono', monospace;
        flex-shrink: 0;
      }
    }

    .alarm-tag { flex-shrink: 0; }

    &.is-critical {
      border-left-color: var(--fa-danger);
      .alarm-dot { background: var(--fa-danger); animation: chip-blink 1.2s infinite; }
    }
    &.is-minor {
      border-left-color: var(--fa-warning);
      .alarm-dot { background: var(--fa-warning); }
    }
    &.is-info {
      border-left-color: var(--fa-text-muted);
      .alarm-dot { background: var(--fa-text-muted); }
    }
  }
}

// 列表项进入动画
.alarm-item-enter-active {
  transition: all 0.3s ease-out;
}
.alarm-item-enter-from {
  opacity: 0;
  transform: translateX(-12px);
}

@keyframes chip-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}
</style>
