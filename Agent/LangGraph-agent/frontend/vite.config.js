import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      // C++ Backend API Gateway
      '/api/v1': {
        target: process.env.FIBER_BACKEND_URL || 'http://localhost:8080',
        changeOrigin: true,
      },
      // WebSocket events from C++ backend
      '/ws/v1': {
        target: process.env.FIBER_BACKEND_URL || 'http://localhost:8080',
        ws: true,
        changeOrigin: true,
      },
      // LangGraph Agent
      '/fiber-agent': {
        target: process.env.AGENT_API_URL || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
