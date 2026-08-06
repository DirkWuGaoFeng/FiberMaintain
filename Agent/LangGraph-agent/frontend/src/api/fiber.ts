/**
 * 光纤维护后端 API — 对接 C++ API Gateway (:8080)
 * 通过 backendClient（baseURL: /api/v1）发起请求
 */
import { backendClient, silentConfig } from './client'
import type { FiberStatsRealtime, TrendPoint, ColoredFiber, BatchFiberResult, FiberColor, FiberSceneDetail } from '@/types/topology'
import type { AlarmRecord } from '@/types/alarm'

/** 获取连纤实时统计（红/黄/绿数量 + 活跃告警数） */
export async function getFiberStatsRealtime(silent = false): Promise<FiberStatsRealtime> {
  const config = silent ? silentConfig() : undefined
  const { data } = await backendClient.get<FiberStatsRealtime>('/fibers/stats/realtime', config)
  return data
}

/** 获取连纤颜色变化趋势（时间范围查询） */
export async function getFiberStatsTrend(startTime: string, endTime: string): Promise<{ points: TrendPoint[] }> {
  const { data } = await backendClient.get<{ points: TrendPoint[] }>('/fibers/stats/trend', {
    params: { start_time: startTime, end_time: endTime },
    ...silentConfig(),
  })
  return data
}

/** 获取所有非绿色连纤（RED + YELLOW，含拓扑信息与场景类型） */
export async function getAllColoredFibers(): Promise<{ fibers: ColoredFiber[] }> {
  const { data } = await backendClient.get<{ fibers: ColoredFiber[] }>('/fibers/colored/all', silentConfig())
  return data
}

/** 按颜色过滤获取连纤 */
export async function getColoredFibers(color: FiberColor): Promise<{ fibers: ColoredFiber[] }> {
  const { data } = await backendClient.get<{ fibers: ColoredFiber[] }>('/fibers/colored', {
    params: { color },
    ...silentConfig(),
  })
  return data
}

/** 批量获取连纤拓扑信息（ids 为空时返回全量） */
export async function batchGetFibers(ids: number[] = []): Promise<{ results: BatchFiberResult[] }> {
  const { data } = await backendClient.post<{ results: BatchFiberResult[] }>(
    '/topology/fibers/batch',
    { fiber_ids: ids },
    silentConfig(),
  )
  return data
}

/** 查询当前活跃告警（按板卡/端口过滤，不传则查询全部） */
export async function getCurrentAlarms(boardId?: number, portId?: number): Promise<{ alarms: AlarmRecord[] }> {
  const params: Record<string, number> = {}
  if (boardId !== undefined) params.board_id = boardId
  if (portId !== undefined) params.port_id = portId
  const { data } = await backendClient.get<{ alarms: AlarmRecord[] }>('/alarms/current', {
    params,
    ...silentConfig(),
  })
  return data
}

/** 获取连纤场景详情（含网元内部拓扑） */
export async function getFiberScene(fiberId: number): Promise<{ found: boolean; scene?: FiberSceneDetail }> {
  const { data } = await backendClient.get<{ found: boolean; scene?: FiberSceneDetail }>(
    `/topology/fibers/${fiberId}/scene`,
    silentConfig(),
  )
  return data
}
