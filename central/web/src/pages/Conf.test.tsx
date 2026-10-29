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
      const body = url.includes('/api/conf/targets')
        ? ['/etc/nginx/nginx.conf']
        : url.includes('/api/conf/apply')
          ? intents
          : confRows
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
  // 관리 대상 추가 폼
  expect(screen.getByRole('button', { name: '대상 추가' })).toBeInTheDocument()
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

test('금고 도장 길로 못 읽는 경로는 수집 실패가 아니라 이 길로는 못 읽음', async () => {
  routed(
    [
      { server_id: 7, hostname: 'dev/shop/web-01', path: '/opt/app/app.conf', status: 'blocked', detail: '박힌 규칙 밖의 경로(/etc 아래 · compose 파일만) — 보내지 않음' },
      { server_id: 7, hostname: 'dev/shop/web-01', path: '/etc/hosts', status: 'error', detail: 'timeout' },
    ],
    [],
  )
  render(<Conf />)
  expect(await screen.findByText('/opt/app/app.conf')).toBeInTheDocument() // 받은 줄을 실제로 그렸나 먼저
  expect(screen.getByText('이 길로는 못 읽음')).toBeInTheDocument()
  expect(screen.getAllByText('수집 실패')).toHaveLength(1)
  expect(screen.getByText(/박힌 규칙 밖의 경로/)).toBeInTheDocument()
})
