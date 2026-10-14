import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import CicdCompare from './CicdCompare'
import { cmpVer, newestBy, verParts } from '../vercmp'
import type { ShapeRow } from '../api'

const ROWS: ShapeRow[] = [
  {
    service: 'shop web', group: 'mall', type: 'web', runtime: 'node', runtime_version: '18', base_image: 'infra/nodejs', base_tag: 'v18',
    deploy: { dev: { path: 'direct', by: 'repo', manual: false }, stg: { path: 'direct', by: 'center', manual: false }, prod: { path: 'image', manual: true, mismatch: true } },
    executor_repo: {
      value: 'shell', guess: false, counts: { shell: 7, docker: 1 },
      groups: [
        { tag: 'old-shell', value: 'shell', guess: false, jobs: ['build', 'push_src'], images: {} },
        { tag: 'new-runner', value: 'docker', guess: true, jobs: ['notify'], images: { notify: 'node:22' } },
      ],
    },
    executor_center: { value: 'docker', guess: true, tags: ['builder'], groups: [{ tag: 'builder', value: 'docker', guess: true, jobs: ['build-image'] }] },
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

test('배포·executor 칸 — 쉬운 말 + 마우스 올리면 뜻', async () => {
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
  // executor: job 별로 한 줄씩 — 적은 쪽은 job 이름, 가장 많은 쪽은 '나머지'
  const shop = table.getByText('mall').closest('tr')!
  const [, , , ...rest] = [...shop.querySelectorAll('td')]
  const repoExec = rest[rest.length - 2]
  const lines = [...repoExec.querySelectorAll('.exec-line')]
  expect(lines.map((l) => l.querySelector('summary')!.textContent)).toEqual(['notify: docker (추정)', '나머지 2개: shell'])
  expect(lines[0].querySelector('summary')).toHaveAttribute('title', expect.stringContaining('Preparing the'))
  // ▸ 를 누르면 아래로 펼쳐서 job 하나하나 + docker 면 쓰는 image
  await userEvent.click(screen.getByLabelText('repo 나머지 2개 펼치기'))
  expect(lines[1]).toHaveAttribute('open')
  expect([...lines[1].querySelectorAll('li')].map((li) => li.textContent)).toEqual([
    'build · image 없음(러너 서버에서 바로)',
    'push_src · image 없음(러너 서버에서 바로)',
  ])
  expect([...lines[0].querySelectorAll('li')].map((li) => li.textContent)).toEqual(['notify · image node:22'])
  // image 를 모으기 전의 옛 데이터(images 없음)는 '없음' 이 아니라 '모름'
  const centerCell = rest[rest.length - 1]
  expect([...centerCell.querySelectorAll('li')].map((li) => li.textContent)).toEqual(['build-image · image 모름(다시 수집 필요)'])
  // job 이 한 종류면 방식만(이름 없이)
  expect(rest[rest.length - 1].querySelector('summary')!.textContent).toBe('docker (추정)')
  // 안 읽은 쪽은 '—' + 이유
  const admin = table.getByText('admin').closest('tr')!
  const adminCells = [...admin.querySelectorAll('td')]
  expect(adminCells[adminCells.length - 1]).toHaveTextContent('—')
  expect(adminCells[adminCells.length - 1].querySelector('span')).toHaveAttribute('title', expect.stringContaining('center CI 를 안 읽음'))
  expect(screen.getByRole('columnheader', { name: 'executor · repo' })).toBeInTheDocument()
  // 런타임·베이스 이미지·start.sh 는 config 탭 몫 — 이 표엔 없음
  const heads = screen.getAllByRole('columnheader').map((h) => h.textContent)
  expect(heads).not.toContain('런타임')
  expect(heads).not.toContain('베이스 이미지')
  expect(heads).not.toContain('start.sh')
  expect(table.queryByText(/node 18/)).toBeNull()
  expect(heads).not.toContain('CI 변수') // 변수 개수는 의미가 적어 뺌
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

test('빈 상태 안내', async () => {
  stub([])
  render(<CicdCompare />)
  expect(await screen.findByText(/아직 비교표가 없습니다/)).toBeInTheDocument()
})
