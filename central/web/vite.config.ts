import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 로컬 dev: /api 는 API 로 프록시. 대상은 VITE_API_PROXY 로 조정(기본 :8000). 컨테이너에선 nginx가 프록시.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': process.env.VITE_API_PROXY || 'http://127.0.0.1:8000' },
  },
})
