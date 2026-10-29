import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import Updates from './Updates'

function mockFetch(data: unknown) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(data), { status: 200 })))
}

const ROWS = [
  {
    server_id: 1,
    hostname: 'web-01',
    pending: 2,
    security: 1,
    packages: [
      { name: 'openssl', from: '3.0.2', to: '3.0.13', security: true },
      { name: 'vim', from: '8.2', to: '8.2.5', security: false },
    ],
    collected_at: '2026-09-14T00:00:00+00:00',
  },
  { server_id: 2, hostname: 'db-01', pending: 0, security: 0, packages: [] },
]

test('수집된 업데이트를 렌더하고 아코디언 펼침/접힘', async () => {
  mockFetch(ROWS)
  render(<Updates />)
  // 첫 대기 서버(web-01) 자동 펼침 → openssl 보임
  expect(await screen.findByText('openssl')).toBeInTheDocument()

  await userEvent.click(screen.getByText('web-01'))
  expect(screen.queryByText('openssl')).not.toBeInTheDocument()

  await userEvent.click(screen.getByText('web-01'))
  expect(screen.getByText('openssl')).toBeInTheDocument()
})

test('빈 상태 안내', async () => {
  mockFetch([])
  render(<Updates />)
  expect(await screen.findByText(/수집된 업데이트가 없습니다/)).toBeInTheDocument()
})

test('OS 패치는 10개씩 페이지로', async () => {
  const many = Array.from({ length: 12 }, (_, i) => ({ server_id: i + 1, hostname: `srv-${String(i + 1).padStart(2, '0')}`, pending: 0, security: 0, packages: [] }))
  mockFetch(many)
  localStorage.removeItem('pager:updates')
  render(<Updates />)
  expect(await screen.findByText('1–10 / 12')).toBeInTheDocument()
  expect(screen.queryByText('srv-11')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'OS 패치 다음 페이지' }))
  expect(screen.getByText('srv-11')).toBeInTheDocument()
  expect(screen.queryByText('srv-01')).toBeNull()
})

test('금고 도장 길로 못 읽은 서버는 수집 실패 · 대기 0 이 아니라 이 길로는 못 읽음', async () => {
  mockFetch([
    { server_id: 7, hostname: 'dev/shop/web-01', pending: 0, security: 0, packages: [], error: '', blocked: true, blocked_reason: 'idp-collect: this certificate only runs …' },
    { server_id: 8, hostname: 'dev/shop/web-02', pending: 0, security: 0, packages: [], error: 'timeout' },
  ])
  render(<Updates />)
  expect(await screen.findByText('dev/shop/web-01')).toBeInTheDocument() // 받은 줄을 실제로 그렸나 먼저
  expect(screen.getByText('이 길로는 못 읽음')).toBeInTheDocument()
  expect(screen.getAllByText('수집 실패')).toHaveLength(1) // web-02(진짜 오류)만
  await userEvent.click(screen.getByText('dev/shop/web-01'))
  expect(screen.getByText(/금고 도장으로는 못 읽는 항목 — idp-collect:/)).toBeInTheDocument()
  expect(screen.queryByText('대기 중인 업데이트 없음')).toBeNull()
})
