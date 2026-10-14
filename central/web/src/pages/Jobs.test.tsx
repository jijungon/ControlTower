import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Jobs from './Jobs'

test('감사 로그를 최신순으로 렌더', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(
        JSON.stringify([
          { id: 2, actor: 'runner', action: 'updates.collect', target_type: 'updates', detail: '2대', created_at: '2026-09-14T00:01:00+00:00' },
          { id: 1, actor: 'runner', action: 'server.import', target_type: 'servers', detail: '신규 2/총 2', created_at: '2026-09-14T00:00:00+00:00' },
        ]),
        { status: 200 },
      ),
    ),
  )
  render(<Jobs />)
  expect(await screen.findByText('업데이트 수집')).toBeInTheDocument()
  expect(screen.getByText('서버 임포트')).toBeInTheDocument()
  expect(screen.getByText('신규 2/총 2')).toBeInTheDocument()
})

test('빈 상태 안내', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })))
  render(<Jobs />)
  expect(await screen.findByText(/기록된 작업이 없습니다/)).toBeInTheDocument()
})

test('작업이력은 한 페이지씩(기본 10개) — 다음 페이지·20개씩 보기', async () => {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      calls.push(url)
      const offset = Number(new URL(url, 'http://x').searchParams.get('offset'))
      const limit = Number(new URL(url, 'http://x').searchParams.get('limit'))
      const rows = Array.from({ length: Math.min(limit, 25 - offset) }, (_, i) => ({
        id: 25 - offset - i, actor: 'runner', action: 'cicd.shape', detail: `#${offset + i + 1}`, created_at: '2026-10-14T02:15:32+00:00',
      }))
      return new Response(JSON.stringify(rows), { status: 200, headers: { 'X-Total-Count': '25' } })
    }),
  )
  localStorage.removeItem('pager:jobs')
  render(<Jobs />)
  expect(await screen.findByText('1–10 / 25')).toBeInTheDocument()
  expect(calls[0]).toBe('/api/audit?limit=10&offset=0')
  expect(screen.getByText('#10')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '작업이력 다음 페이지' }))
  expect(await screen.findByText('11–20 / 25')).toBeInTheDocument()
  expect(calls[calls.length - 1]).toBe('/api/audit?limit=10&offset=10')
  fireEvent.click(screen.getByRole('radio', { name: '20개' }))
  expect(await screen.findByText('1–20 / 25')).toBeInTheDocument()
  expect(calls[calls.length - 1]).toBe('/api/audit?limit=20&offset=0')
  expect(screen.getAllByText('2026-10-14 ' + new Date('2026-10-14T02:15:32+00:00').toTimeString().slice(0, 5)).length).toBe(20) // 시각은 읽기 쉽게
})
