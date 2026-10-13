import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Cicd from './Cicd'

// 비교표(/api/cicd/shape)는 빈 목록, 나머지(/api/cicd)는 주어진 응답
function stubCicd(body: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => new Response(String(url).includes('/shape') ? '[]' : body, { status: 200 })),
  )
}

test('파이프라인 상태 배지 렌더', async () => {
  stubCicd(
    JSON.stringify([
      { service: 'admin', project: 'group/aggregator-admin', has_cicd: true, status: 'success', ref: 'main', collected_at: '2026-09-14T00:00:00+00:00' },
      { service: 'pnl', project: 'group/pnl', has_cicd: true, status: 'failed', ref: 'main' },
      { service: 'legacy', project: 'group/legacy', has_cicd: false, status: null },
    ]),
  )
  render(<Cicd />)
  expect(await screen.findByText('admin')).toBeInTheDocument()
  expect(screen.getByText('성공')).toBeInTheDocument()
  expect(screen.getByText('실패')).toBeInTheDocument()
  expect(screen.getAllByText('없음').length).toBeGreaterThanOrEqual(1) // legacy: CI/CD·상태 모두 없음
  expect(screen.getByRole('button', { name: '서비스 추가' })).toBeInTheDocument() // 대상 추가 폼
})

test('빈 상태 안내', async () => {
  stubCicd('[]')
  render(<Cicd />)
  expect(await screen.findByText(/등록된 서비스가 없습니다/)).toBeInTheDocument()
})
