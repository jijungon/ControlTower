import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import CicdCompare, { cmpVer, newestBy, verParts } from './CicdCompare'
import type { ShapeRow } from '../api'

const ROWS: ShapeRow[] = [
  {
    service: 'shop web', group: 'shop', runtime: 'node', runtime_version: '18', base_image: 'infra/nodejs', base_tag: 'v18',
    deploy: { dev: { path: 'direct', manual: false }, prod: { path: 'image', manual: true, mismatch: true } },
    executor_repo: { value: 'shell', guess: false }, executor_center: { value: 'docker', guess: true },
    startup: true, env_keys: 4, env_changed_at: new Date().toISOString(),
  },
  {
    service: 'shop admin', group: 'shop', runtime: 'node', runtime_version: '20', base_image: 'node', base_tag: '20-slim',
    deploy: { dev: { path: 'image', manual: false }, prod: { path: 'image', manual: true } },
    executor_repo: { value: 'docker', guess: false }, executor_center: null,
    startup: false, env_keys: 2,
  },
  {
    service: 'billing', runtime: 'java', runtime_version: '17', base_image: 'infra/springboot', base_tag: '0.1.3-java17',
    deploy: { dev: { path: 'build', manual: null } }, startup: null, env_keys: null,
  },
]

function stub(rows: unknown) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(rows), { status: 200 })))
}

test('버전 비교 헬퍼 — 3.10 > 3.9, v18 < 20', () => {
  expect(cmpVer(verParts('3.10.1'), verParts('3.9'))).toBe(1)
  expect(cmpVer(verParts('v18'), verParts('20-slim'))).toBe(-1)
  expect(cmpVer(verParts('1.27'), verParts('1.27.0'))).toBe(0)
  expect(verParts('latest')).toEqual([])
  const m = newestBy(ROWS, (r) => (r.runtime && r.runtime_version ? [r.runtime, r.runtime_version] : null))
  expect(m.get('node')).toBe('20')
  expect(m.get('java')).toBe('17')
})

test('같은 종류 중 최신이 아닌 버전만 빨간 칸', async () => {
  stub(ROWS)
  render(<CicdCompare />)
  const old = await screen.findByText('⚠ node 18')
  expect(old).toHaveClass('ver--old')
  expect(old).toHaveAttribute('title', '최신(node 20)보다 오래됨')
  const table = within(screen.getByRole('table'))
  expect(table.getByText('node 20')).not.toHaveClass('ver--old') // 최신
  expect(table.getByText('java 17')).not.toHaveClass('ver--old') // 혼자라 비교 대상 없음
  // 베이스 이미지는 '이미지 이름이 같은 것끼리'만 비교 → 여기선 다 혼자라 빨간 칸 없음
  expect(table.getByText('infra/nodejs:v18')).not.toHaveClass('ver--old')
  expect(screen.getByText(/1칸/)).toBeInTheDocument()
})

test('배포 경로·executor·start.sh·env 칸', async () => {
  stub(ROWS)
  render(<CicdCompare />)
  await screen.findByText('shop web')
  expect(screen.getAllByText('직배포').length).toBe(1)
  expect(screen.getByText('빌드만')).toBeInTheDocument()
  expect(screen.getByText('compose 다름')).toBeInTheDocument()
  expect(screen.getByText('docker?')).toHaveAttribute('title', '추정 — runners 표에 없는 태그')
  expect(screen.getByText('있음')).toBeInTheDocument()
  expect(screen.getByText('없음')).toBeInTheDocument()
  expect(screen.getByText('오늘 변경')).toBeInTheDocument()
  // 데이터에 있는 환경만 칸으로(dev·prod), 없는 환경(stg)은 칸 없음
  expect(screen.getByRole('columnheader', { name: 'dev' })).toBeInTheDocument()
  expect(screen.queryByRole('columnheader', { name: 'stg' })).toBeNull()
})

test('런타임 필터', async () => {
  stub(ROWS)
  render(<CicdCompare />)
  await screen.findByText('shop web')
  fireEvent.change(screen.getByLabelText('런타임 필터'), { target: { value: 'java 17' } })
  expect(screen.queryByText('shop web')).toBeNull()
  expect(screen.getByText('billing')).toBeInTheDocument()
})

test('빈 상태 안내', async () => {
  stub([])
  render(<CicdCompare />)
  expect(await screen.findByText(/아직 비교표가 없습니다/)).toBeInTheDocument()
})
