/**
 * WebSocket 实时事件类型定义
 * 对应 C++ 后端 ws://host:8081/ws/v1/events 推送的事件
 */

/** 事件类型 */
export type WsEventType = 'alarm' | 'fiber_color' | 'fiber_stats' | 'pong'

/** 告警事件 */
export interface AlarmEvent {
  type: 'alarm'
  alarm_id?: number
  fiber_id: number
  alarm_level: 'CRITICAL' | 'MAJOR' | 'MINOR' | 'WARNING'
  alarm_type?: string
  message?: string
  timestamp: string
}

/** 光纤色标变更事件 */
export interface FiberColorEvent {
  type: 'fiber_color'
  fiber_id: number
  old_color: 'RED' | 'YELLOW' | 'GREEN'
  new_color: 'RED' | 'YELLOW' | 'GREEN'
  timestamp: string
}

/** 光纤统计更新事件 */
export interface FiberStatsEvent {
  type: 'fiber_stats'
  data: {
    total_fibers?: number
    red_count?: number
    yellow_count?: number
    green_count?: number
    avg_spanloss?: number
  }
  timestamp: string
}

/** WebSocket 事件联合类型 */
export type WsEvent = AlarmEvent | FiberColorEvent | FiberStatsEvent | { type: 'pong' }

/** WebSocket 连接状态 */
export type WsConnectionState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting'
