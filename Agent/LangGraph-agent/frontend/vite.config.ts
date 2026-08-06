import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { resolve } from 'path'

/**
 * Vite 配置 — Fiber Agent Frontend v7.1
 *
 * 代理策略:
 *   /api/v1/knowledge|threads|graph|memory|metrics → Agent (FastAPI :8000)
 *   /api/v1/* (其余) → C++ 后端 API Gateway (:8080)
 *   /ws/v1 → Agent WebSocket (:8000)
 *   /fiber-agent, /invoke, /health, /metrics → Agent (FastAPI :8000)
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd())
  const agentUrl = env.VITE_AGENT_URL || 'http://localhost:8000'
  const backendUrl = env.VITE_BACKEND_URL || 'http://localhost:8080'
  const wsUrl = env.VITE_WS_URL || 'ws://localhost:8081'

  return {
    plugins: [
      vue(),
      AutoImport({
        imports: ['vue', 'vue-router', 'pinia', 'vue-i18n'],
        resolvers: [ElementPlusResolver()],
        dts: 'src/auto-imports.d.ts',
      }),
      Components({
        resolvers: [ElementPlusResolver()],
        dts: 'src/components.d.ts',
      }),
    ],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
      },
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: {
        // Agent 专属 API（优先匹配，长路径优先）
        '/api/v1/knowledge': { target: agentUrl, changeOrigin: true },
        '/api/v1/threads': { target: agentUrl, changeOrigin: true },
        '/api/v1/graph': { target: agentUrl, changeOrigin: true },
        '/api/v1/memory': { target: agentUrl, changeOrigin: true },
        '/api/v1/metrics': { target: agentUrl, changeOrigin: true },
        '/api/v1/degradation': { target: agentUrl, changeOrigin: true },
        '/api/v1/rules': { target: agentUrl, changeOrigin: true },
        '/api/v1/traces': { target: agentUrl, changeOrigin: true },
        '/api/batch': { target: agentUrl, changeOrigin: true },
        // C++ 后端 API Gateway
        '/api/v1': { target: backendUrl, changeOrigin: true },
        // WebSocket 实时事件（Agent 后端提供）
        '/ws/v1': { target: agentUrl, ws: true, changeOrigin: true },
        // LangServe Agent 路由
        '/fiber-agent': { target: agentUrl, changeOrigin: true },
        '/invoke': { target: agentUrl, changeOrigin: true },
        '/health': { target: agentUrl, changeOrigin: true },
        '/metrics': { target: agentUrl, changeOrigin: true },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            'element-plus': ['element-plus', '@element-plus/icons-vue'],
            echarts: ['echarts', 'vue-echarts'],
            'vue-flow': ['@vue-flow/core', '@vue-flow/background', '@vue-flow/controls', '@vue-flow/minimap'],
            vendor: ['vue', 'vue-router', 'pinia', 'axios', 'vue-i18n'],
          },
        },
      },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      include: ['tests/unit/**/*.spec.ts'],
      coverage: {
        provider: 'v8',
        include: ['src/**/*.{ts,vue}'],
        exclude: ['src/auto-imports.d.ts', 'src/components.d.ts'],
      },
    },
  }
})
