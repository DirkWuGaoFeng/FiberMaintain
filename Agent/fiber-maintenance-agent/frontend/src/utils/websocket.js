/**
 * WebSocket 管理器：支持心跳保活、自动重连、消息分发
 */
export class WebSocketManager {
  constructor(url, options = {}) {
    this.url = url
    this.heartbeatInterval = options.heartbeatInterval || 15000
    this.reconnectBackoff = options.reconnectBackoff || [3, 6, 12, 30]
    this.reconnectAttempts = 0
    this.ws = null
    this.heartbeatTimer = null
    this.listeners = new Map()
  }

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return

    try {
      this.ws = new WebSocket(this.url)
      
      this.ws.onopen = () => {
        console.log('[WS] 连接已建立')
        this.reconnectAttempts = 0
        this._startHeartbeat()
        this._emit('open')
      }

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'pong') return // 忽略心跳响应
          this._emit('message', data)
        } catch (e) {
          console.warn('[WS] 消息解析失败:', event.data)
        }
      }

      this.ws.onclose = (event) => {
        console.warn(`[WS] 连接关闭: ${event.code}`)
        this._stopHeartbeat()
        this._emit('close', event)
        this._scheduleReconnect()
      }

      this.ws.onerror = (error) => {
        console.error('[WS] 发生错误:', error)
        this._emit('error', error)
      }
    } catch (err) {
      console.error('[WS] 创建连接失败:', err)
      this._scheduleReconnect()
    }
  }

  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(typeof data === 'string' ? data : JSON.stringify(data))
    }
  }

  on(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, [])
    }
    this.listeners.get(event).push(callback)
  }

  _emit(event, data) {
    const callbacks = this.listeners.get(event) || []
    callbacks.forEach(cb => cb(data))
  }

  _startHeartbeat() {
    this._stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      this.send({ type: 'ping' })
    }, this.heartbeatInterval)
  }

  _stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  _scheduleReconnect() {
    if (this.reconnectAttempts >= this.reconnectBackoff.length) {
      console.error('[WS] 达到最大重连次数，停止重连')
      this._emit('max_retries')
      return
    }
    const delay = this.reconnectBackoff[this.reconnectAttempts] * 1000
    console.log(`[WS] 将在 ${delay / 1000}s 后尝试第 ${this.reconnectAttempts + 1} 次重连...`)
    setTimeout(() => {
      this.reconnectAttempts++
      this.connect()
    }, delay)
  }

  disconnect() {
    this._stopHeartbeat()
    if (this.ws) {
      this.ws.close(1000, '客户端主动断开')
    }
  }
}