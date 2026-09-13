import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        timeout: 120000,
      }
    }
  },
  preview: {
    // 生产预览（局域网共享用）：默认继承 server.proxy，这里显式声明保证一致
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        timeout: 120000,
      }
    }
  },
  build: {
    // 手动分包：不常变的三方库独立成 chunk，利用浏览器长期缓存；
    // echarts 与 react 分开，避免一方的更新导致另一方缓存失效
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom'],
          'vendor-echarts': ['echarts', 'echarts/core', 'echarts-for-react', 'echarts/charts', 'echarts/components', 'echarts/renderers'],
          'vendor-icons': ['lucide-react'],
        },
      },
    },
  },
})
