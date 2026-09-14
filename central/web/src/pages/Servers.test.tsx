import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Servers from './Servers'

function routed(servers: unknown, groups: unknown = [], serversOk = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/api/groups')) return new Response(JSON.stringify(groups), { status: 200 })
      return new Response(JSON.stringify(servers), { status: serversOk ? 200 : 500 })
    }),
  )
}

test('서버 목록에 그룹·태그를 렌더', async () => {
  routed(
    [{ id: 1, hostname: 'web-01', ip: '10.0.0.1', ssh_user: 'deploy', status: 'online', group: 'prod', tags: ['edge', 'nginx'] }],
    [{ id: 1, name: 'prod', count: 1 }],
  )
  render(<Servers />)
  expect(await screen.findByText('web-01')).toBeInTheDocument()
  expect(screen.getByText('10.0.0.1')).toBeInTheDocument()
  expect(screen.getByText('prod')).toBeInTheDocument()
  expect(screen.getByText('edge')).toBeInTheDocument()
})

test('빈 상태 안내', async () => {
  routed([], [])
  render(<Servers />)
  expect(await screen.findByText(/임포트된 서버가 없습니다/)).toBeInTheDocument()
})

test('API 에러 상태 안내', async () => {
  routed({}, [], false)
  render(<Servers />)
  expect(await screen.findByText(/API에 연결하지 못했습니다/)).toBeInTheDocument()
})
