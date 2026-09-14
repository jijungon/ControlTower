import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Servers from './Servers'

function mockFetch(data: unknown, ok = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(data), { status: ok ? 200 : 500 })),
  )
}

test('서버 목록을 렌더', async () => {
  mockFetch([
    { id: 1, hostname: 'web-01', ip: '10.0.0.1', ssh_user: 'deploy', status: 'online', credential_alias: 'k1', access_control: 'ncloud' },
  ])
  render(<Servers />)
  expect(await screen.findByText('web-01')).toBeInTheDocument()
  expect(screen.getByText('10.0.0.1')).toBeInTheDocument()
  expect(screen.getByText('ncloud')).toBeInTheDocument()
})

test('빈 상태 안내', async () => {
  mockFetch([])
  render(<Servers />)
  expect(await screen.findByText(/임포트된 서버가 없습니다/)).toBeInTheDocument()
})

test('API 에러 상태 안내', async () => {
  mockFetch({}, false)
  render(<Servers />)
  expect(await screen.findByText(/API에 연결하지 못했습니다/)).toBeInTheDocument()
})
