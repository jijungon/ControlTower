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
