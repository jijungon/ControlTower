import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import HostStatusBar from './HostStatusBar'
import { installAuthExpiryWatch, resetAuthExpiryForTest } from '../authExpiry'
import type { HostStatus } from '../api'

const base: HostStatus = { source: 'idp', state: 'ok', reasons: [], host: 'test-host', problems: [], unread: [], written_age_seconds: 20 }

function serve(...replies: (HostStatus[] | 'fail')[]) {
  const fetchMock = vi.fn(async () => {
    const r = replies.length > 1 ? replies.shift()! : replies[0]
    if (r === 'fail') throw new TypeError('Failed to fetch')
    return new Response(JSON.stringify(r), { status: 200 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const realFetch = globalThis.fetch

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  window.fetch = realFetch
  resetAuthExpiryForTest()
})

test('아무도 안 올렸으면(기능 꺼짐) 아무것도 안 보임', async () => {
  const f = serve([])
  const { container } = render(<HostStatusBar />)
  await vi.waitFor(() => expect(f).toHaveBeenCalled())
  expect(container).toBeEmptyDOMElement()
})

test('정상 — 초록 한 줄', async () => {
  serve([base])
  render(<HostStatusBar />)
  const line = await screen.findByRole('status')
  expect(line).toHaveClass('host-status--ok')
  expect(line).toHaveTextContent('● IdP 서버 정상 · test-host')
  expect(line).toHaveTextContent('방금 기록')
})

test('경보 — 문제와 못 본 것을 둘 다(못 본 것을 빼면 "문제 없음" 처럼 보인다)', async () => {
  serve([{ ...base, state: 'alert', problems: ['systemd 실패: a.service'], unread: ['breakglass: 계정이 없다'], reasons: ['상태 기록이 6분째 멈춤 — 적는 쪽 타이머 확인'] }])
  render(<HostStatusBar />)
  const line = await screen.findByRole('alert')
  expect(line).toHaveClass('host-status--alert')
  expect(line).toHaveTextContent('⚠ IdP 서버 경보 · test-host')
  expect(line).toHaveTextContent('문제: systemd 실패: a.service')
  expect(line).toHaveTextContent('못 본 것: breakglass: 계정이 없다')
  expect(line).toHaveTextContent('상태 기록이 6분째 멈춤')
})

test('모름 — 회색, 이유와 마지막 기록', async () => {
  serve([{ ...base, state: 'unknown', reasons: ['상태 파일을 못 읽음 — 파일 없음'], written_age_seconds: 360 }])
  render(<HostStatusBar />)
  const line = await screen.findByRole('alert')
  expect(line).toHaveClass('host-status--unknown')
  expect(line).toHaveTextContent('○ IdP 서버 상태 모름 · test-host')
  expect(line).toHaveTextContent('상태 파일을 못 읽음 — 파일 없음')
  expect(line).toHaveTextContent('마지막 기록 6분 전')
  expect(screen.queryByText(/정상/)).toBeNull()
})

test('보이던 상태를 못 불러오게 되면 초록을 그대로 두지 않고 "모름"', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  serve([base], 'fail')
  render(<HostStatusBar />)
  expect(await screen.findByRole('status')).toHaveTextContent('정상')
  await act(() => vi.advanceTimersByTimeAsync(30_000))
  const line = await screen.findByRole('alert')
  expect(line).toHaveTextContent('서버 상태 모름')
  expect(screen.queryByRole('status')).toBeNull()
})

test('처음부터 못 불러오면(아직 한 번도 못 봄) 아무것도 안 보임 — 다른 표들이 "못 닿음" 을 보여 줌', async () => {
  const f = serve('fail')
  const { container } = render(<HostStatusBar />)
  await vi.waitFor(() => expect(f).toHaveBeenCalled())
  expect(container).toBeEmptyDOMElement()
})

test('로그인이 만료되면 서버 상태 줄은 내리고(초록을 남기지 않음) — 이유는 맨 위 로그인 만료 한 줄이 말함', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const loginRedirect = { type: 'opaqueredirect', ok: false, status: 0, headers: new Headers() } as unknown as Response
  let n = 0
  vi.stubGlobal('fetch', vi.fn(async () => (n++ === 0 ? new Response(JSON.stringify([base]), { status: 200 }) : loginRedirect)))
  installAuthExpiryWatch(window)
  render(<HostStatusBar />)
  expect(await screen.findByRole('status')).toHaveTextContent('정상')
  await act(() => vi.advanceTimersByTimeAsync(30_000))
  await vi.waitFor(() => expect(screen.queryByRole('status')).toBeNull())
  expect(screen.queryByText(/서버 상태 모름/)).toBeNull() // 두 줄로 겹치지 않게
})
