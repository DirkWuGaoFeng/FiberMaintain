import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.DEERFLOW_API_URL || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})