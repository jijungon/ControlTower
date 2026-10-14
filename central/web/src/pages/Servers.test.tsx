import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Servers from './Servers'

test('서버 탭 = IdP 연동 후 서버 ↔ 항목 연결 자리, 서버 목록(IP·접속키)은 안 보임 + /etc 설정 파일은 그대로', async () => {
  const fetchMock = vi.fn(async (_url: string) => new Response('[]', { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  render(<Servers />)
  expect(screen.getByRole('heading', { name: '서버' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '서버 ↔ 항목 연결' })).toBeInTheDocument()
  expect(document.querySelector('.placeholder')).toHaveTextContent(/서버 목록은 IdP 연동 후 IdP 에서 가져와요/)
  // 서버 정보는 IdP 에서 → 서버 목록 API 를 부르지 않고, 검색·IP 칸도 없음
  expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/api/servers'))).toBe(false)
  expect(screen.queryByPlaceholderText('서버 · IP · user 검색')).toBeNull()
  expect(await screen.findByRole('heading', { name: '서버 설정 파일 (/etc)' })).toBeInTheDocument()
})
