import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import CollectButton from './CollectButton'
import type { CollectStatus } from '../api'

const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 })

afterEach(() => vi.useRealTimers())

test('다시 수집 — 요청됨 → 수집 중 → 완료면 표를 다시 불러옴(한 번), 그 뒤엔 확인 멈춤', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  let status: CollectStatus = { request: null, collector: { name: 'srv', alive: true } }
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      status = { ...status, request: { id: 5, kind: 'shape', status: 'pending' } }
      return json({ id: 5, kind: 'shape', status: 'pending', reused: false })
    }
    return json(status)
  })
  vi.stubGlobal('fetch', fetchMock)
  const onDone = vi.fn()
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  render(<CollectButton onDone={onDone} />)
  await user.click(await screen.findByRole('button', { name: '다시 수집' }))
  expect(fetchMock.mock.calls.some(([u, i]) => u === '/api/collect/requests' && i?.method === 'POST')).toBe(true)
  expect(await screen.findByText('요청됨 — 수집기를 기다리는 중')).toBeInTheDocument()
  // 수집기가 가져감 → 수집 중(버튼 잠김)
  status = { ...status, request: { id: 5, kind: 'shape', status: 'running' } }
  await act(() => vi.advanceTimersByTimeAsync(2000))
  expect(screen.getByRole('button', { name: '수집 중…' })).toBeDisabled()
  expect(screen.getByRole('status')).toHaveTextContent('수집 중 — GitLab 을 다시 읽는 중')
  // 완료 → 표를 다시 불러옴(한 번만), 요약은 마우스
  status = { ...status, request: { id: 5, kind: 'shape', status: 'done', finished_at: '2026-10-15T01:00:00+00:00', message: '서비스 17개 · config 17줄' } }
  await act(() => vi.advanceTimersByTimeAsync(2000))
  expect(onDone).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('status')).toHaveTextContent(/^완료 · /)
  expect(screen.getByRole('status')).toHaveAttribute('title', '서비스 17개 · config 17줄')
  expect(screen.getByRole('button', { name: '다시 수집' })).toBeEnabled()
  const calls = fetchMock.mock.calls.length
  await act(() => vi.advanceTimersByTimeAsync(6000))
  expect(fetchMock.mock.calls.length).toBe(calls) // 끝나면 2초 확인을 멈춤
  expect(onDone).toHaveBeenCalledTimes(1)
})

test('수집기가 꺼져 있으면 알림 · 실패면 이유', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({ request: null, collector: null })))
  const { unmount } = render(<CollectButton onDone={() => {}} />)
  expect(await screen.findByText('수집기 꺼짐')).toHaveAttribute('title', expect.stringContaining('python -m runner.cli agent'))
  unmount()
  vi.stubGlobal('fetch', vi.fn(async () => json({ request: { id: 1, kind: 'shape', status: 'pending' }, collector: { name: 'srv', alive: false } })))
  const second = render(<CollectButton onDone={() => {}} />)
  expect(await screen.findByText('요청됨 — ⚠ 수집기가 꺼져 있어요')).toHaveClass('collect-state--warn')
  second.unmount()
  vi.stubGlobal('fetch', vi.fn(async () => json({ request: { id: 2, kind: 'shape', status: 'failed', message: 'GitLab 토큰이 없어 멈춤(repo)' }, collector: { name: 'srv', alive: true } })))
  render(<CollectButton onDone={() => {}} />)
  expect(await screen.findByText('실패 · GitLab 토큰이 없어 멈춤(repo)')).toHaveClass('collect-state--fail')
})
