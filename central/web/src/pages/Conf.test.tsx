import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Conf from './Conf'

const CONF_ROWS = [
  { server_id: 1, hostname: 'web-01', path: '/etc/nginx/nginx.conf', status: 'synced' },
  { server_id: 2, hostname: 'web-02', path: '/etc/nginx/nginx.conf', status: 'drift', detail: 'gzip 누락' },
]

function routed(confRows: unknown, intents: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const body = url.includes('/api/conf/apply') ? intents : confRows
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
}

test('드리프트 배지 + 드리프트 행에 적용 계획 버튼', async () => {
  routed(CONF_ROWS, [])
  render(<Conf />)
  expect(await screen.findByText('동기화됨')).toBeInTheDocument()
  expect(screen.getByText('드리프트')).toBeInTheDocument()
  expect(screen.getByText('gzip 누락')).toBeInTheDocument()
  // drift 행에만 적용 계획 버튼(1개)
  expect(screen.getAllByRole('button', { name: '적용 계획' })).toHaveLength(1)
})

test('적용 대기 섹션 — 승인 버튼과 diff 토글', async () => {
  const intents = [
    {
      id: 5,
      server_id: 2,
      hostname: 'web-02',
      path: '/etc/nginx/nginx.conf',
      status: 'pending',
      diff: '--- current\n+++ baseline\n-worker\n+gzip on;\n',
    },
  ]
  routed(CONF_ROWS, intents)
  render(<Conf />)
  expect(await screen.findByText('적용 대기 · 이력')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '승인' })).toBeInTheDocument()
  // 이미 계획된 (web-02) drift 행은 '계획됨' 으로 표시 → 적용 계획 버튼 없음
  expect(screen.queryByRole('button', { name: '적용 계획' })).not.toBeInTheDocument()
})
