import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Versions from './Versions'

test('버전 매트릭스를 렌더', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(
        JSON.stringify([
          { server_id: 1, hostname: 'build-01', tools: { node: '20.11.1', java: '17.0.9', docker: '24.0.7' }, collected_at: '2026-09-14T00:00:00+00:00' },
        ]),
        { status: 200 },
      ),
    ),
  )
  render(<Versions />)
  expect(await screen.findByText('build-01')).toBeInTheDocument()
  expect(screen.getByText('20.11.1')).toBeInTheDocument()
  expect(screen.getByText('17.0.9')).toBeInTheDocument()
  expect(screen.getByText('24.0.7')).toBeInTheDocument()
})

test('빈 상태 안내', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })))
  render(<Versions />)
  expect(await screen.findByText(/수집된 버전이 없습니다/)).toBeInTheDocument()
})
