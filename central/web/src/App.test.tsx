import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })))
})

test('기본 탭은 대시보드, 탭 클릭 시 전환', async () => {
  render(<App />)
  expect(await screen.findByRole('heading', { name: '대시보드' })).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'config' }))
  expect(screen.getByRole('heading', { name: 'repo 프로젝트' })).toBeInTheDocument() // config 는 repo 보기부터
})

test('탭 5개 — 서버 → config → 빌드·배포 → OS 패치·작업이력', async () => {
  render(<App />)
  await screen.findByRole('heading', { name: '대시보드' })
  expect(screen.getAllByRole('button').filter((b) => b.classList.contains('tab')).map((b) => b.textContent)).toEqual([
    '대시보드', '서버', 'config', '빌드·배포', 'OS 패치·작업이력',
  ]) // 서버(IdP 연동 후 연결 자리) → 무엇으로 만드나(config) → 어떻게 배포하나(빌드·배포)
  await userEvent.click(screen.getByRole('button', { name: '서버' }))
  expect(screen.getByRole('heading', { name: '누가 · 어디로' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '빌드·배포' }))
  expect(screen.getByRole('heading', { name: '빌드 · 배포' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '서비스 비교' })).toBeInTheDocument()
  // 빌드·배포 = 방식만 — 따로 된 버전·파이프라인 섹션은 없음
  expect(screen.queryByRole('heading', { name: '버전' })).toBeNull()
  expect(screen.queryByRole('heading', { name: '파이프라인 상태' })).toBeNull()
  // 출처는 '표 읽는 법'(접힘) 맨 아래로
  expect(screen.getByText('출처').nextElementSibling).toHaveTextContent(/^repo·center GitLab\(\.gitlab-ci\.yml/)
  await userEvent.click(screen.getByRole('button', { name: 'config' }))
  expect(screen.getByRole('heading', { name: 'repo 프로젝트' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'OS 패치·작업이력' }))
  expect(screen.getByRole('heading', { name: 'OS 패치' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '작업이력 (전체)' })).toBeInTheDocument()
})

function serveMe(me: object | 'fail') {
  const fetchMock = vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/api/me')) {
      if (me === 'fail') throw new TypeError('Failed to fetch')
      return new Response(JSON.stringify(me), { status: 200 })
    }
    if (u.includes('/api/access'))
      return new Response(JSON.stringify({ state: 'off', viewer: { email: null, role: '' }, envs: [], people: [] }), { status: 200 })
    return new Response('[]', { status: 200 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const tabNames = () => screen.getAllByRole('button').filter((b) => b.classList.contains('tab')).map((b) => b.textContent)

test('개발자(server-admin 아님)는 서버 탭 하나만, 바로 열리고 /etc 칸도 없음 — 다른 탭 API 는 부르지 않음', async () => {
  const f = serveMe({ authenticated: true, email: 'dev@example.com', groups: ['developer'] })
  render(<App />)
  expect(await screen.findByRole('heading', { name: '누가 · 어디로' })).toBeInTheDocument()
  expect(tabNames()).toEqual(['서버'])
  expect(screen.queryByRole('heading', { name: '대시보드' })).toBeNull()
  expect(screen.queryByRole('heading', { name: '서버 설정 파일 (/etc)' })).toBeNull()
  const called = f.mock.calls.map(([u]) => String(u))
  expect(called.some((u) => u.includes('/api/conf') || u.includes('/api/cicd') || u.includes('/api/servers'))).toBe(false)
})

test('운영자 · 둘 다 · 로그인 없음(none) · /api/me 실패는 탭 5개 그대로', async () => {
  for (const me of [
    { authenticated: true, email: 'a@example.com', groups: ['server-admin'] },
    { authenticated: true, email: 'b@example.com', groups: ['developer', 'server-admin'] },
    { authenticated: false, email: null, groups: [] },
    'fail' as const,
  ]) {
    serveMe(me)
    const { unmount } = render(<App />)
    await screen.findByRole('heading', { name: '대시보드' })
    expect(tabNames()).toEqual(['대시보드', '서버', 'config', '빌드·배포', 'OS 패치·작업이력'])
    unmount()
  }
})

test('누군지 알기 전에는 탭을 그리지 않는다(개발자에게 다른 탭이 잠깐 뜨지 않게)', async () => {
  let release: (r: Response) => void = () => {}
  vi.stubGlobal('fetch', vi.fn((url: string) =>
    String(url).includes('/api/me') ? new Promise<Response>((r) => { release = r }) : Promise.resolve(new Response('[]', { status: 200 }))))
  render(<App />)
  expect(screen.getByText('불러오는 중…')).toBeInTheDocument()
  expect(screen.queryAllByRole('button').filter((b) => b.classList.contains('tab'))).toEqual([])
  release(new Response(JSON.stringify({ authenticated: true, email: 'd@example.com', groups: ['developer'] }), { status: 200 }))
  expect(await screen.findByRole('heading', { name: '누가 · 어디로' })).toBeInTheDocument()
})
