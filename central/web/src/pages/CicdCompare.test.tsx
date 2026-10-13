import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import CicdCompare from './CicdCompare'
import { cmpVer, newestBy, verParts } from '../vercmp'
import type { ShapeRow } from '../api'

const ROWS: ShapeRow[] = [
  {
    service: 'shop web', group: 'mall', type: 'web', runtime: 'node', runtime_version: '18', base_image: 'infra/nodejs', base_tag: 'v18',
    deploy: { dev: { path: 'direct', by: 'repo', manual: false }, stg: { path: 'direct', by: 'center', manual: false }, prod: { path: 'image', manual: true, mismatch: true } },
    executor_repo: { value: 'shell', guess: false }, executor_center: { value: 'docker', guess: true },
    startup: true, env_keys: 4, env_changed_at: new Date().toISOString(),
  },
  {
    service: 'shop admin', group: 'mall', type: 'admin', runtime: 'node', runtime_version: '20', base_image: 'node', base_tag: '20-slim',
    deploy: { dev: { path: 'image', manual: false }, prod: { path: 'image', manual: true } },
    executor_repo: { value: 'docker', guess: false }, executor_center: null,
    startup: false, env_keys: 2,
  },
  {
    service: 'billing', runtime: 'java', runtime_version: '17', base_image: 'infra/springboot', base_tag: '0.1.3-java17',
    deploy: { dev: { path: 'build', manual: null }, prod: { path: 'direct', by: 'compose', manual: null } }, startup: null, env_keys: null,
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
  expect(screen.getByText(/오래된 버전 1칸/)).toBeInTheDocument()
})

test('배포·executor·start.sh·CI 변수 칸 — 쉬운 말 + 마우스 올리면 뜻', async () => {
  stub(ROWS)
  render(<CicdCompare />)
  const table = within(await screen.findByRole('table'))
  // 배포 칸: 윗줄 방식 + 아랫줄 누가(repo/center) — 칸 전체에 마우스를 올리면 뜻
  const repoCell = table.getByText('repo', { selector: '.cell-sub' }).parentElement!
  expect(repoCell).toHaveTextContent('파일 복사repo')
  expect(repoCell).toHaveAttribute('title', expect.stringContaining('직배포'))
  expect(table.getByText('center', { selector: '.cell-sub' }).parentElement).toHaveAttribute('title', expect.stringContaining('center CI'))
  expect(table.getAllByText('수동', { selector: '.cell-sub' }).length).toBeGreaterThan(0)
  expect(table.getByText('빌드만')).toBeInTheDocument()
  expect(table.getByText('compose 기준', { selector: '.cell-sub' }).parentElement).toHaveAttribute('title', expect.stringContaining('짐작'))
  expect(table.getByText('⚠ compose 다름')).toHaveAttribute('title', expect.stringContaining('파일 복사'))
  expect(table.getByText('(추정)').parentElement).toHaveAttribute('title', expect.stringContaining('runners 표에 없어'))
  // start.sh: 있음은 노랑, 없음은 초록
  expect(table.getByText('있음')).toHaveClass('badge--warn')
  expect(table.getByText('없음')).toHaveClass('badge--ok')
  expect(table.getByText('오늘 바뀜')).toBeInTheDocument()
  expect(screen.getByText('표 읽는 법')).toBeInTheDocument()
  // 데이터에 있는 환경만 칸으로(dev·stg·prod), 없는 환경(lab)은 칸 없음
  expect(screen.getByRole('columnheader', { name: 'dev' })).toBeInTheDocument()
  expect(screen.queryByRole('columnheader', { name: 'lab' })).toBeNull()
})

test('그룹 → 서비스 → 타입: 맨 앞 그룹 칸이 그룹의 모든 줄을 덮음', async () => {
  stub([...ROWS, { service: 'shop web', group: 'outlet', type: 'web', note: '옛 사본' }])
  render(<CicdCompare />)
  const table = within(await screen.findByRole('table'))
  expect(screen.getAllByRole('columnheader').slice(0, 3).map((h) => h.textContent)).toEqual(['그룹', '서비스', '타입'])
  // 그룹 칸: 이름순, 그룹 없는 건 맨 끝 '기타'. rowspan = 그 그룹의 줄 수
  const groups = [...document.querySelectorAll('td.grp-cell')].map((td) => [td.firstChild?.textContent, td.getAttribute('rowspan')])
  expect(groups).toEqual([['mall', '2'], ['outlet', '1'], ['기타', '1']])
  // mall 안의 shop 서비스는 web·admin 두 줄을 한 칸으로
  expect(table.getAllByText('shop')[0].closest('td')).toHaveAttribute('rowspan', '2')
  expect(table.getByText('옛 사본')).toBeInTheDocument()
  // 경계 줄: 그룹 시작 3개, 그룹 안에서 서비스가 바뀌는 곳은 없음(각 그룹 서비스 1개)
  expect(document.querySelectorAll('tr.grp-start').length).toBe(3)
  // 그룹 필터
  fireEvent.change(screen.getByLabelText('그룹 필터'), { target: { value: 'outlet' } })
  expect([...document.querySelectorAll('td.grp-cell')].map((td) => td.firstChild?.textContent)).toEqual(['outlet'])
})

test('config 연결 시 start.sh 상태 색', async () => {
  stub([{ service: 'x web', type: 'web', start_state: 'legacy', startup: true }, { service: 'y web', type: 'web', start_state: 'leftover', startup: true }])
  render(<CicdCompare />)
  const table = within(await screen.findByRole('table'))
  expect(await table.findByText('사용 중')).toHaveClass('badge--danger')
  expect(table.getByText('파일만 남음')).toHaveClass('badge--warn')
})

test('런타임 필터', async () => {
  stub(ROWS)
  render(<CicdCompare />)
  await screen.findByText('shop')
  fireEvent.change(screen.getByLabelText('런타임 필터'), { target: { value: 'java 17' } })
  expect(within(screen.getByRole('table')).queryByText('shop')).toBeNull()
  expect(screen.getByText('billing')).toBeInTheDocument()
})

test('빈 상태 안내', async () => {
  stub([])
  render(<CicdCompare />)
  expect(await screen.findByText(/아직 비교표가 없습니다/)).toBeInTheDocument()
})
