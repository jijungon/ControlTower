import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { installAuthExpiryWatch, isAuthExpired, looksLikeLoginRedirect, resetAuthExpiryForTest } from './authExpiry'
import AuthExpiredBanner from './components/AuthExpiredBanner'
import ConfigRepo from './pages/ConfigRepo'

// 로그인(사내 IdP 프록시) 세션이 끝나 /api 가 로그인으로 돌려진 응답 — 브라우저는 redirect: 'manual' 이면 이렇게 준다
const LOGIN_REDIRECT = { type: 'opaqueredirect', ok: false, status: 0, headers: new Headers() } as unknown as Response
const realFetch = globalThis.fetch

beforeEach(() => {
  resetAuthExpiryForTest()
  localStorage.clear()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.fetch = realFetch
})

test('로그인으로 돌려진 응답만 만료로 본다 — 우리 API 의 거절(JSON)과 정상은 아님', () => {
  const res = (status: number, type?: string) => new Response('x', { status, headers: type ? { 'content-type': type } : {} })
  expect(looksLikeLoginRedirect(LOGIN_REDIRECT)).toBe(true)
  expect(looksLikeLoginRedirect(res(401, 'text/html'))).toBe(true) // 프록시의 로그인 페이지
  expect(looksLikeLoginRedirect(res(403))).toBe(true)
  expect(looksLikeLoginRedirect(res(401, 'application/json'))).toBe(false) // 우리 API 의 거절
  expect(looksLikeLoginRedirect(res(409, 'application/json'))).toBe(false)
  expect(looksLikeLoginRedirect(res(200, 'application/json'))).toBe(false)
})

test('/api 만 redirect 를 안 따라가게 부르고, 돌려지면 만료 — 다른 주소·네트워크 끊김은 만료 아님', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  const inner = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({ url, init })
    if (url.includes('/down')) throw new TypeError('Failed to fetch')
    if (url.startsWith('/api/')) return LOGIN_REDIRECT
    return new Response('ok')
  })
  const win = { fetch: inner } as unknown as Window
  installAuthExpiryWatch(win)

  await win.fetch('/assets/app.js')
  expect(calls[0].init?.redirect).toBeUndefined() // /api 가 아니면 손대지 않음
  expect(isAuthExpired()).toBe(false)

  await expect(win.fetch('/api/down')).rejects.toThrow('Failed to fetch') // API 꺼짐 · 네트워크 끊김
  expect(isAuthExpired()).toBe(false)

  await win.fetch('/api/cicd/shape', { headers: { a: 'b' } })
  expect(calls[2].init).toMatchObject({ redirect: 'manual', headers: { a: 'b' } })
  expect(isAuthExpired()).toBe(true)
})

test('로그인 만료 — 위에 한 줄 안내, 표·버튼은 "만료" 로(서버 고장 · "아직 수집 없음" 처럼 보이지 않게)', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => LOGIN_REDIRECT))
  installAuthExpiryWatch(window)
  render(
    <>
      <AuthExpiredBanner />
      <ConfigRepo />
    </>,
  )
  expect(await screen.findByRole('alert')).toHaveTextContent('로그인이 만료됐어요 — 새로고침해 주세요')
  expect(await screen.findByText('로그인이 만료돼 repo 표를 불러오지 못했어요 — 새로고침해 주세요.')).toBeInTheDocument()
  expect(await screen.findByText('로그인 만료 — 새로고침해 주세요')).toBeInTheDocument() // [다시 수집] 옆
  expect(screen.queryByText(/아직 repo 를 읽지 않았습니다/)).toBeNull()
  expect(screen.queryByText(/아직 수집 없음/)).toBeNull()
  expect(screen.queryByText(/중앙 API 상태를 확인하세요/)).toBeNull()
  await userEvent.click(screen.getByRole('tab', { name: 'center' }))
  expect(await screen.findByText('로그인이 만료돼 config 를 불러오지 못했어요 — 새로고침해 주세요.')).toBeInTheDocument()
})

test('API 가 꺼졌을 때는 예전처럼 "못 닿음" — 로그인 만료 안내는 안 뜸', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
  installAuthExpiryWatch(window)
  render(
    <>
      <AuthExpiredBanner />
      <ConfigRepo />
    </>,
  )
  expect(await screen.findByText('repo 표를 불러오지 못했습니다 — 중앙 API 상태를 확인하세요.')).toBeInTheDocument()
  expect(await screen.findByText('ControlTower 에 못 닿음')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.queryByText(/아직 수집 없음/)).toBeNull() // 못 불러온 것을 '아직 수집 없음' 으로 말하지 않음
})
