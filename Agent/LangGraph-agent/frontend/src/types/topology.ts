/**
 * 连纤拓扑相关类型定义
 * 对应 C++ 后端 TopologyService / FiberMaintService 接口响应
 */

/** 光纤颜色枚举 */
export type FiberColor = 'RED' | 'YELLOW' | 'GREEN'

/** 连纤基础信息（对应 TopologyService BatchGetFibers 响应） */
export interface FiberInfo {
  fiber_id: number
  src_board_id: number
  src_port_id: number
  src_ne_id: number
  dst_board_id: number
  dst_port_id: number
  dst_ne_id: number
  created_at?: string
}

/** 带颜色的连纤（对应 GET /api/v1/fibers/colored/all 响应） */
export interface ColoredFiber {
  fiber: FiberInfo
  color: FiberColor
  scenario_type: number
}

/** 实时统计（对应 GET /api/v1/fibers/stats/realtime） */
export interface FiberStatsRealtime {
  total_fibers: number
  red_count: number
  yellow_count: number
  green_count: number
  total_colored: number
  active_alarms: number
}

/** 趋势数据点（对应 GET /api/v1/fibers/stats/trend） */
export interface TrendPoint {
  timestamp: string
  red_count: number
  yellow_count: number
  total_colored: number
}

/** 趋势查询时间范围 */
export type TrendRange = 'hour' | 'day' | 'week'

/** 拓扑图节点（网元抽象） */
export interface TopoNode {
  /** 网元 ID */
  id: number
  /** 显示标签 */
  label: string
  /** 布局坐标 */
  x: number
  y: number
  /** 关联的板卡数量 */
  boardCount: number
}

/** 拓扑图边（连纤） */
export interface TopoEdge {
  fiber: FiberInfo
  color: FiberColor
}

/** BatchGetFibers 响应中的单条结果 */
export interface BatchFiberResult {
  found: boolean
  fiber?: FiberInfo
  error_message?: string
}

/** 板卡信息（对应 GetFiberScene 响应中的 board 字段） */
export interface BoardInfo {
  board_id: number
  ne_id: number
  board_type: number  // 1=ACTIVE, 2=PASSIVE
}

/** 场景详情（对应 GET /api/v1/topology/fibers/{id}/scene） */
export interface FiberSceneDetail {
  scene_type: number            // 1=场景1(有源-有源), 2=场景2(有源-无源)
  inter_ne_fiber_id: number
  inter_ne_fiber: FiberInfo
  src_active_board?: BoardInfo
  dst_active_board?: BoardInfo
  ne_internal_fibers: FiberInfo[]  // 网元内部连纤
  passive_boards: BoardInfo[]      // 无源板卡列表
}

/** 拓扑视图模式 */
export type TopoViewMode = 'colored' | 'full'

/** 拓扑图板卡节点（布局计算后） */
export interface BoardNode {
  board_id: number
  ne_id: number
  /** 是否为无源板卡 */
  is_passive: boolean
  x: number
  y: number
}

/** 网元容器（布局计算后） */
export interface NeContainer {
  ne_id: number
  label: string
  x: number
  y: number
  width: number
  height: number
  boards: BoardNode[]
}
