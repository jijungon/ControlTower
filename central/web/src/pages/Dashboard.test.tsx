import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Dashboard from './Dashboard'

const SERVERS = [
  { id: 1, hostname: 'web-01', ssh_user: 'deploy', status: 'online', last_checked_at: '2026-09-14T00:00:00+00:00' },
  { id: 2, hostname: 'web-02', ssh_user: 'deploy', status: 'unknown' },
]
const CONF = [
  { server_id: 1, hostname: 'web-01', path: '/etc/nginx/nginx.conf', status: 'synced' },
  { server_id: 2, hostname: 'web-02', path: '/etc/nginx/nginx.conf', status: 'drift' },
]
const UPDATES = [
  { server_id: 1, hostname: 'web-01', pending: 2, security: 1, packages: [] },
  { server_id: 2, hostname: 'web-02', pending: 1, security: 0, packages: [] },
]

function routedFetch(url: string) {
  const body = url.includes('/api/servers')
    ? SERVERS
    : url.includes('/api/updates')
      ? UPDATES
      : url.includes('/api/conf')
        ? CONF
        : []
  return new Response(JSON.stringify(body), { status: 200 })
}

test('실집계를 카드에 표시', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => routedFetch(url)))
  render(<Dashboard />)
  // 온라인 1/2 (web-01 online, web-02 unknown)
  expect(await screen.findByText('1/2')).toBeInTheDocument()
  // 대기 업데이트 = 2 + 1 = 3
  expect(screen.getByText('3')).toBeInTheDocument()
  // 라벨 존재
  expect(screen.getByText('보안 패치')).toBeInTheDocument()
})

test('API 실패 시 안내', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
  render(<Dashboard />)
  expect(await screen.findByText(/API 연결 실패/)).toBeInTheDocument()
})
