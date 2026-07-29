/**
 * WebSocket Manager: heartbeat keep-alive, auto-reconnect, event dispatch
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
        console.log('[WS] Connected')
        this.reconnectAttempts = 0
        this._startHeartbeat()
        this._emit('open')
      }

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'pong') return
          this._emit('message', data)
        } catch (e) {
          console.warn('[WS] Parse error:', event.data)
        }
      }

      this.ws.onclose = (event) => {
        console.warn(`[WS] Closed: ${event.code}`)
        this._stopHeartbeat()
        this._emit('close', event)
        this._scheduleReconnect()
      }

      this.ws.onerror = (error) => {
        console.error('[WS] Error:', error)
        this._emit('error', error)
      }
    } catch (err) {
      console.error('[WS] Create failed:', err)
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
      console.error('[WS] Max reconnect reached')
      this._emit('max_retries')
      return
    }
    const delay = this.reconnectBackoff[this.reconnectAttempts] * 1000
    setTimeout(() => {
      this.reconnectAttempts++
      this.connect()
    }, delay)
  }

  disconnect() {
    this._stopHeartbeat()
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect')
    }
  }
}
