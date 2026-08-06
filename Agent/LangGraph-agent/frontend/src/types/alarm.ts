/**
 * 告警相关类型定义
 * 对应 C++ 后端 AlarmService 接口响应
 */

/** 告警级别 */
export type AlarmLevel = 'CRITICAL' | 'MAJOR' | 'MINOR' | 'WARNING' | 'UNSPECIFIED'

/** 告警记录（对应 GET /api/v1/alarms/current 响应） */
export interface AlarmRecord {
  board_id: number
  port_id: number
  alarm_level: AlarmLevel
  raised_at: string
}

/** 告警统计汇总 */
export interface AlarmSummary {
  total: number
  critical: number
  minor: number
  unspecified: number
}
