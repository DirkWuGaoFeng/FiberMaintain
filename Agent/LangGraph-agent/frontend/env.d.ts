/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

interface ImportMetaEnv {
  /** Agent FastAPI 服务地址 */
  readonly VITE_AGENT_URL: string
  /** C++ 后端 API Gateway 地址 */
  readonly VITE_BACKEND_URL: string
  /** C++ 后端 WebSocket 地址 */
  readonly VITE_WS_URL: string
  /** 应用标题 */
  readonly VITE_APP_TITLE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
