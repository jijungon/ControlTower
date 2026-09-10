import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 로컬 dev: /api 는 로컬 API(:8000)로 프록시. 컨테이너에선 nginx가 프록시.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
