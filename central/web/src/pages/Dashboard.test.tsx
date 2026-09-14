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
const VERSIONS = [
  { kind: 'server', name: 'old-01', tools: { node: '10.24.0', python: '3.6.8' } }, // EOL
  { kind: 'server', name: 'new-01', tools: { node: '20.11.1' } }, // OK
]

function routedFetch(url: string) {
  const body = url.includes('/api/servers')
    ? SERVERS
    : url.includes('/api/updates')
      ? UPDATES
      : url.includes('/api/versions')
        ? VERSIONS
        : url.includes('/api/conf')
          ? CONF
          : []
  return new Response(JSON.stringify(body), { status: 200 })
}

test('실집계 + EOL/보안 경고를 표시', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => routedFetch(url)))
  render(<Dashboard />)
  expect(await screen.findByText('1/2')).toBeInTheDocument() // 온라인 1/2
  expect(screen.getByText('3')).toBeInTheDocument() // 대기 업데이트 2+1
  expect(screen.getByText('보안 패치')).toBeInTheDocument()
  // EOL 경고: old-01 의 node 10 · python 3.6 이 경고 표에 뜸(툴 2개 → 이름 2행)
  expect(await screen.findByText('node 10.24.0')).toBeInTheDocument()
  expect(screen.getByText('python 3.6.8')).toBeInTheDocument()
  expect(screen.getAllByText('old-01')).toHaveLength(2)
  expect(screen.queryByText('new-01')).not.toBeInTheDocument() // node 20 은 경고 아님
})

test('API 실패 시 안내', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
  render(<Dashboard />)
  expect(await screen.findByText(/API 연결 실패/)).toBeInTheDocument()
})
