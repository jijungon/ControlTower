import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })))
})

test('기본 탭은 대시보드, 탭 클릭 시 전환', async () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: '대시보드' })).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'config' }))
  expect(screen.getByRole('heading', { name: 'repo 프로젝트' })).toBeInTheDocument() // config 는 repo 보기부터
})

test('탭 5개 — 서버 → config → 빌드·배포 → OS 패치·작업이력', async () => {
  render(<App />)
  expect(screen.getAllByRole('button').filter((b) => b.classList.contains('tab')).map((b) => b.textContent)).toEqual([
    '대시보드', '서버', 'config', '빌드·배포', 'OS 패치·작업이력',
  ]) // 서버(IdP 연동 후 연결 자리) → 무엇으로 만드나(config) → 어떻게 배포하나(빌드·배포)
  await userEvent.click(screen.getByRole('button', { name: '서버' }))
  expect(screen.getByRole('heading', { name: '서버 ↔ 항목 연결' })).toBeInTheDocument()
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
