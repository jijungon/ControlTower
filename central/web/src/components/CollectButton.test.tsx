import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import CollectButton from './CollectButton'
import type { CollectStatus } from '../api'

const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 })

afterEach(() => vi.useRealTimers())

test('다시 수집 — 요청 → 수집 중 → 완료면 표를 다시 불러옴(한 번), 그 뒤엔 확인 멈춤', async () => {
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
  render(<CollectButton onDone={onDone} asOf="2026-10-15T00:50:00+00:00" />)
  const button = await screen.findByRole('button', { name: '다시 수집' })
  await vi.waitFor(() => expect(button).toBeEnabled()) // 수집기 켜짐 → 버튼 켜짐
  // 평소엔 시각 하나만 — 표 머리줄의 '데이터 기준' 을 여기로 옮김(두 군데 X)
  expect(screen.getByRole('status')).toHaveTextContent(/^데이터 기준 2026-10-15/)
  await user.click(button)
  expect(fetchMock.mock.calls.some(([u, i]) => u === '/api/collect/requests' && i?.method === 'POST')).toBe(true)
  expect(await screen.findByText('요청됨 — 곧 시작')).toBeInTheDocument()
  // 수집기가 가져감 → 수집 중(버튼 잠김)
  status = { ...status, request: { id: 5, kind: 'shape', status: 'running' } }
  await act(() => vi.advanceTimersByTimeAsync(2000))
  expect(screen.getByRole('button', { name: '수집 중…' })).toBeDisabled()
  expect(screen.getByRole('status')).toHaveTextContent('수집 중 — GitLab 을 다시 읽는 중')
  // 완료 → 표를 다시 불러옴(한 번만), 요약은 마우스
  status = { ...status, request: { id: 5, kind: 'shape', status: 'done', finished_at: new Date().toISOString(), message: '서비스 17개 · config 17줄' } }
  await act(() => vi.advanceTimersByTimeAsync(2000))
  expect(onDone).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('status')).toHaveTextContent(/^데이터 기준 .* · 방금 갱신$/)
  expect(screen.getByRole('status')).toHaveClass('collect-state--ok')
  expect(screen.getByRole('status')).toHaveAttribute('title', '서비스 17개 · config 17줄')
  expect(screen.getByRole('button', { name: '다시 수집' })).toBeEnabled()
  const calls = fetchMock.mock.calls.length
  await act(() => vi.advanceTimersByTimeAsync(20000))
  expect(fetchMock.mock.calls.length).toBe(calls) // 끝나고 수집기도 켜져 있으면 확인을 멈춤
  expect(onDone).toHaveBeenCalledTimes(1)
})

test('수집기가 꺼져 있으면 버튼도 꺼짐 — 10초마다 확인해서 켜지면 다시 켜짐', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  let status: CollectStatus = { request: null, collector: null }
  vi.stubGlobal('fetch', vi.fn(async () => json(status)))
  render(<CollectButton onDone={() => {}} />)
  expect(await screen.findByText('수집기 꺼짐 · 아직 수집 없음')).toHaveAttribute('title', expect.stringContaining('make agent'))
  const button = screen.getByRole('button', { name: '다시 수집' })
  expect(button).toBeDisabled()
  expect(button).toHaveAttribute('title', expect.stringContaining('docker compose 의 collector'))
  status = { request: null, collector: { name: 'srv', alive: true } }
  await act(() => vi.advanceTimersByTimeAsync(10000))
  expect(button).toBeEnabled()
  expect(screen.getByRole('status')).toHaveTextContent('아직 수집 없음') // 꺼짐 표시가 사라지고 시각만
})

test('꺼진 사이 남은 요청 · 실패면 이유', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({ request: { id: 1, kind: 'shape', status: 'pending' }, collector: { name: 'srv', alive: false } })))
  const first = render(<CollectButton onDone={() => {}} />)
  expect(await screen.findByText('요청됨 — 수집기가 꺼져 있어요(켜면 바로 처리)')).toHaveClass('collect-state--warn')
  first.unmount()
  vi.stubGlobal('fetch', vi.fn(async () => json({ request: { id: 2, kind: 'shape', status: 'failed', message: '10분 동안 수집기가 가져가지 않아 취소' }, collector: { name: 'srv', alive: true } })))
  render(<CollectButton onDone={() => {}} />)
  expect(await screen.findByText('실패 · 10분 동안 수집기가 가져가지 않아 취소 · 아직 수집 없음')).toHaveClass('collect-state--fail')
})
