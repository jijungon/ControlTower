import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Versions from './Versions'

const ROWS = [
  { kind: 'server', name: 'build-01', tools: { node: '20.11.1', java: '17.0.9', docker: '24.0.7' }, collected_at: '2026-09-14T00:00:00+00:00' },
  { kind: 'repo', name: 'aggregator_web', tools: { node: '20.11', nest: '10.3' } },
]

function routed(versions: unknown, targets: unknown = []) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const body = url.includes('/repo-targets') ? targets : versions
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
}

test('서버·repo 버전 매트릭스를 렌더', async () => {
  routed(ROWS)
  render(<Versions />)
  expect(await screen.findByText('build-01')).toBeInTheDocument()
  expect(screen.getByText('aggregator_web')).toBeInTheDocument()
  expect(screen.getByText('24.0.7')).toBeInTheDocument()
  expect(screen.getByText('10.3')).toBeInTheDocument() // repo 선언본(nest)
  expect(screen.getByText('빌드')).toBeInTheDocument() // 구분 태그
  // GitLab 선언본 대상 섹션 + 추가 폼
  expect(screen.getByText('GitLab 선언본 대상')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '대상 추가' })).toBeInTheDocument()
})

test('빈 상태 안내', async () => {
  routed([], [])
  render(<Versions />)
  expect(await screen.findByText(/수집된 버전이 없습니다/)).toBeInTheDocument()
  expect(screen.getByText(/등록된 대상이 없습니다/)).toBeInTheDocument()
})
