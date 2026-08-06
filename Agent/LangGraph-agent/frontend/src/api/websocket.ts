/**
 * WebSocket 管理器 — 心跳保活 + 指数退避重连 + 事件分发
 * 连接 C++ 后端 ws://host:8081/ws/v1/events
 */
import type { WsEvent, WsConnectionState } from '@/types/events'

export interface WebSocketOptions {
  /** 心跳间隔（毫秒） */
  heartbeatInterval?: number
  /** 重连退避序列（秒） */
  reconnectBackoff?: number[]
  /** 连接状态变更回调 */
  onStateChange?: (state: WsConnectionState) => void
  /** 事件回调 */
  onEvent?: (event: WsEvent) => void
}

export class WebSocketManager {
  private url: string
  private options: Required<Pick<WebSocketOptions, 'heartbeatInterval' | 'reconnectBackoff'>> & WebSocketOptions
  private ws: WebSocket | null = null
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private reconnectAttempts = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private manualClose = false
  private _state: WsConnectionState = 'disconnected'

  constructor(url: string, options: WebSocketOptions = {}) {
    this.url = url
    this.options = {
      heartbeatInterval: 15000,
      reconnectBackoff: [3, 6, 12, 30],
      ...options,
    }
  }

  get state(): WsConnectionState {
    return this._state
  }

  /** 建立连接 */
  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    this.manualClose = false
    this.setState('connecting')

    try {
      this.ws = new WebSocket(this.url)

      this.ws.onopen = () => {
        this.reconnectAttempts = 0
        this.setState('connected')
        this.startHeartbeat()
      }

      this.ws.onmessage = (event: MessageEvent) => {
        try {
          const data = JSON.parse(String(event.data)) as WsEvent
          if (data.type === 'pong') return
          this.options.onEvent?.(data)
        } catch {
          // 忽略无法解析的消息
        }
      }

      this.ws.onclose = () => {
        this.stopHeartbeat()
        if (!this.manualClose) {
          this.setState('reconnecting')
          this.scheduleReconnect()
        } else {
          this.setState('disconnected')
        }
      }

      this.ws.onerror = () => {
        // onclose 会紧随触发，在 onclose 中处理重连
      }
    } catch {
      this.setState('reconnecting')
      this.scheduleReconnect()
    }
  }

  /** 发送消息 */
  send(data: Record<string, unknown> | string): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(typeof data === 'string' ? data : JSON.stringify(data))
    }
  }

  /** 主动断开（不重连） */
  disconnect(): void {
    this.manualClose = true
    this.stopHeartbeat()
    this.clearReconnectTimer()
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect')
      this.ws = null
    }
    this.setState('disconnected')
  }

  /** 手动重连 */
  reconnect(): void {
    this.clearReconnectTimer()
    this.reconnectAttempts = 0
    this.connect()
  }

  private setState(state: WsConnectionState): void {
    this._state = state
    this.options.onStateChange?.(state)
  }

  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      this.send({ type: 'ping' })
    }, this.options.heartbeatInterval)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private scheduleReconnect(): void {
    const backoff = this.options.reconnectBackoff
    if (this.reconnectAttempts >= backoff.length) {
      this.setState('disconnected')
      return
    }
    const delay = backoff[this.reconnectAttempts] * 1000
    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++
      this.connect()
    }, delay)
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }
}
