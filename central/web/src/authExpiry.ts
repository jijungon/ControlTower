import { useSyncExternalStore } from 'react'

// 로그인(사내 IdP 프록시) 세션이 끝나면 /api 요청이 로그인 페이지로 돌려진다. 화면은 이미 받아 둔 그대로라
// 각 표가 '못 불러옴 · 아직 수집 없음' 으로 보여 서버 고장처럼 보였다(2026-10-20) → 그 경우를 따로 알아챈다.
// - /api 는 redirect 를 따라가지 않게(manual) 부른다: 우리 API 는 redirect 를 쓰지 않으므로 돌려진 응답 = 로그인으로 보냄
// - 401·403 이어도 우리 API 의 거절은 JSON — 프록시의 로그인 응답(HTML)만 만료로 본다
// - 네트워크 끊김·API 꺼짐(fetch 예외)은 만료가 아님 → 기존 '못 닿음' 문구 그대로
let expired = false
const listeners = new Set<() => void>()

function markExpired() {
  if (expired) return
  expired = true
  listeners.forEach((fn) => fn())
}

export function looksLikeLoginRedirect(res: Response): boolean {
  if (res.type === 'opaqueredirect') return true
  if (res.status === 401 || res.status === 403) return !(res.headers.get('content-type') ?? '').includes('application/json')
  return false
}

function isApi(input: RequestInfo | URL): boolean {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  const path = url.startsWith('/') ? url : new URL(url, window.location.href).pathname
  return path.startsWith('/api/') || path === '/api'
}

export function installAuthExpiryWatch(win: Window = window): void {
  const orig = win.fetch.bind(win)
  win.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    if (!isApi(input)) return orig(input, init)
    const res = await orig(input, { redirect: 'manual', ...init })
    if (looksLikeLoginRedirect(res)) markExpired()
    return res
  }
}

export function isAuthExpired(): boolean {
  return expired
}

export function useAuthExpired(): boolean {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn)
      return () => {
        listeners.delete(fn)
      }
    },
    () => expired,
  )
}

export function resetAuthExpiryForTest(): void {
  expired = false
}
