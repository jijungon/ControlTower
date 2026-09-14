import { defineConfig, devices } from '@playwright/test'

// 풀스택 E2E: 실제 API(uvicorn, 임시 SQLite) + web(vite dev, /api 프록시=테스트 API) 를
// 함께 띄우고 브라우저로 검증. 파이썬은 CT_PYTHON 으로 교체 가능(로컬은 .venv, CI는 python).
const API_PORT = 8099
const WEB_PORT = 5199
const PYTHON = process.env.CT_PYTHON || 'python'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? 'list' : [['list']],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      // 매 실행 새 DB → 시드가 누적되지 않음
      command: `rm -f ./e2e_web.db && ${PYTHON} -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT} --log-level warning`,
      cwd: '../api',
      env: {
        DATABASE_URL: 'sqlite:///./e2e_web.db',
        CT_API_TOKEN: 'e2e-web-token',
        CT_SECRET: 'e2e',
        PYTHONPATH: '.',
      },
      url: `http://127.0.0.1:${API_PORT}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${WEB_PORT}`,
      env: { VITE_API_PROXY: `http://127.0.0.1:${API_PORT}` },
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
