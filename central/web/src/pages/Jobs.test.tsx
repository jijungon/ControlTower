import { render, screen } from '@testing-library/react'
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
