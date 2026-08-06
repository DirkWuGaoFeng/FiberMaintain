/**
 * Axios 客户端 — 统一错误处理 + 请求拦截
 */
import axios from 'axios'
import type { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

/** 后端 API Gateway 客户端（C++ 服务 :8080） */
export const backendClient = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

/** Agent 服务客户端（FastAPI :8000） */
export const agentClient = axios.create({
  baseURL: '',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
})

/** API 错误结构 */
export interface ApiError {
  status: number
  message: string
  detail?: string
}

// 请求拦截器：附加请求 ID + 记录开始时间
function requestInterceptor(config: InternalAxiosRequestConfig) {
  config.headers.set('X-Request-ID', crypto.randomUUID().slice(0, 16))
  ;(config as unknown as Record<string, unknown>)._startTime = performance.now()
  return config
}

// 响应拦截器：统一错误提示
function responseErrorInterceptor(error: AxiosError<{ detail?: string }>) {
  const status = error.response?.status ?? 0
  const detail = error.response?.data?.detail

  let message: string
  switch (status) {
    case 400:
      message = detail || '请求参数错误'
      break
    case 401:
      message = '未授权访问'
      break
    case 404:
      message = '接口不存在'
      break
    case 429:
      message = '请求过于频繁，请稍后重试'
      break
    case 500:
      message = detail || '服务器内部错误'
      break
    case 503:
      message = '服务暂不可用（可能处于降级模式）'
      break
    default:
      message = error.code === 'ECONNABORTED' ? '请求超时' : detail || `网络错误 (${status || error.code})`
  }

  // 静默请求不弹提示（通过 config 标记）
  const silent = (error.config as unknown as Record<string, unknown>)?._silent
  if (!silent) {
    ElMessage.error(message)
  }

  return Promise.reject({ status, message, detail } as ApiError)
}

for (const client of [backendClient, agentClient]) {
  client.interceptors.request.use(requestInterceptor)
  client.interceptors.response.use((res) => res, responseErrorInterceptor)
}

/** 标记请求为静默（不弹错误提示） */
export function silentConfig(extra: Record<string, unknown> = {}) {
  return { _silent: true, ...extra } as Record<string, unknown> as import('axios').AxiosRequestConfig
}
