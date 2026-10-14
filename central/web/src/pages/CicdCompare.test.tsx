import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import CicdCompare, { collectRunners } from './CicdCompare'
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
    executor_repo: {
      value: 'docker', guess: false,
      groups: [{ tag: 'r1', value: 'docker', guess: false, why: 'job 로그 #41', jobs: ['build'], images: {}, default_image: 'docker:27', runner_name: 'build-01' }],
    },
    executor_center: null,
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
  const repoChip = table.getByText('repo', { selector: '.cell-sub' }).parentElement!
  expect(repoChip).toHaveTextContent('파일 복사repo')
  expect(repoChip.closest('[title]')).toHaveAttribute('title', expect.stringContaining('직배포'))
  expect(table.getByText('center', { selector: '.cell-sub' }).closest('[title]')).toHaveAttribute('title', expect.stringContaining('center CI'))
  expect(table.getAllByText('수동', { selector: '.cell-sub' }).length).toBeGreaterThan(0)
  expect(table.getByText('빌드만')).toBeInTheDocument()
  expect(table.getByText('compose 기준', { selector: '.cell-sub' }).closest('[title]')).toHaveAttribute('title', expect.stringContaining('짐작'))
  // 색: 이미지 초록(표준) · 파일 복사 노랑(옮길 곳) · 빌드만 회색, compose 로 짐작한 칸은 점선
  expect(repoChip).toHaveClass('path-chip', 'path-chip--direct')
  expect(table.getByText('빌드만')).toHaveClass('path-chip--build')
  expect(table.getAllByText('수동', { selector: '.cell-sub' })[0].parentElement).toHaveClass('path-chip--image')
  expect(table.getByText('compose 기준', { selector: '.cell-sub' }).parentElement).toHaveClass('path-chip--direct', 'path-chip--guess')
  expect(table.getByText('⚠ compose 다름')).toHaveAttribute('title', expect.stringContaining('파일 복사'))
  // executor: job 별로 한 줄씩 — 적은 쪽은 job 이름, 가장 많은 쪽은 '나머지'
  const shop = table.getByText('mall').closest('tr')!
  const [, , , ...rest] = [...shop.querySelectorAll(':scope > td')]
  const repoExec = rest[rest.length - 2]
  const lines = [...repoExec.querySelectorAll('.exec-line')]
  expect(lines.map((l) => l.querySelector('summary')!.textContent)).toEqual(['notify: docker (추정)', '나머지 2개: shell'])
  expect(lines[0].querySelector('summary')).toHaveAttribute('title', expect.stringContaining('Preparing the'))
  // ▸ 를 누르면 아래로 펼쳐서 job 하나하나 + docker 면 쓰는 image
  await userEvent.click(screen.getByLabelText('repo 나머지 2개 펼치기'))
  expect(lines[1]).toHaveAttribute('open')
  // 펼친 job 표: job | image | 러너 (열 맞춤)
  const jobRows = (el: Element) => [...el.querySelectorAll('table.mini-table tbody tr')].map((tr) => [...tr.querySelectorAll('td')].map((td) => td.textContent).join(' | '))
  expect([...lines[1].querySelectorAll('table.mini-table th')].map((th) => th.textContent)).toEqual(['job', 'image', '러너'])
  expect(jobRows(lines[1])).toEqual(['build | 없음 — 러너 서버에서 바로 | old-shell', 'push_src | 없음 — 러너 서버에서 바로 | old-shell'])
  expect(jobRows(lines[0])).toEqual(['notify | node:22 | new-runner'])
  // image 를 모으기 전의 옛 데이터(images 없음)는 '없음' 이 아니라 '모름'
  const centerCell = rest[rest.length - 1]
  expect(jobRows(centerCell)).toEqual(['build-image | 모름(다시 수집 필요) | builder'])
  // job 이 한 종류면 방식만(이름 없이)
  expect(rest[rest.length - 1].querySelector('summary')!.textContent).toBe('docker (추정)')
  // 안 읽은 쪽은 '—' + 이유
  const admin = table.getByText('admin').closest('tr')!
  const adminCells = [...admin.querySelectorAll(':scope > td')]
  expect(adminCells[adminCells.length - 1]).toHaveTextContent('—')
  expect(adminCells[adminCells.length - 1].querySelector('span')).toHaveAttribute('title', expect.stringContaining('center CI 를 안 읽음'))
  expect(screen.getByRole('columnheader', { name: 'executor · repo' })).toBeInTheDocument()
  // job 로그로 확정된 줄: 마우스에 근거(job 번호), 펼치면 image: 없는 job 의 러너 기본 이미지
  const adminRepo = adminCells[adminCells.length - 2]
  expect(adminRepo.querySelector('summary')).toHaveAttribute('title', expect.stringContaining('확정(job 로그 #41)'))
  expect(jobRows(adminRepo)).toEqual(['build | docker:27 (러너 기본) | r1'])
  expect(adminRepo.querySelector('td[title^="등록된 러너"]')).toHaveAttribute('title', '등록된 러너: build-01')
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
  fireEvent.click(within(screen.getByRole('radiogroup', { name: '그룹 필터' })).getByRole('radio', { name: 'outlet' }))
  expect([...document.querySelectorAll('td.grp-cell')].map((td) => td.firstChild?.textContent)).toEqual(['outlet'])
})

test('빈 상태 안내', async () => {
  stub([])
  render(<CicdCompare />)
  expect(await screen.findByText(/아직 비교표가 없습니다/)).toBeInTheDocument()
})

test('러너 표 — 태그마다 방식 · 확인 근거 · 등록된 러너 이름 · 쓰는 서비스', async () => {
  stub(ROWS)
  render(<CicdCompare />)
  const head = await screen.findByRole('heading', { name: '러너' })
  const table = within(head.closest('.section-head')!.nextElementSibling as HTMLElement)
  const row = (tag: string) => table.getByText(tag, { selector: 'td' }).closest('tr')!
  expect(row('r1')).toHaveTextContent(/^repor1docker확정 · job 로그 #41build-01shop admin · job 1개$/)
  expect(row('old-shell')).toHaveTextContent('확정 · runners 표')
  expect(row('new-runner')).toHaveTextContent('추정')
  expect(row('builder')).toHaveTextContent(/^centerbuilder/)
  // 같은 태그를 runners 표와 job 로그가 둘 다 확정하면 로그 근거를 보여줌
  const rows2 = [
    { ...ROWS[0], service: 'a', executor_repo: { value: 'shell', guess: false, groups: [{ tag: 'brand', value: 'shell', guess: false, why: 'runners 표', jobs: ['x'] }] } },
    { ...ROWS[0], service: 'b', executor_repo: { value: 'shell', guess: false, groups: [{ tag: 'brand', value: 'shell', guess: false, why: 'job 로그 #9', jobs: ['y'], runner_name: 'gw-01' }] } },
  ]
  expect(collectRunners(rows2 as ShapeRow[]).filter((x) => x.tag === 'brand')).toMatchObject([{ why: 'job 로그 #9', name: 'gw-01', jobs: 2 }])
})

test('GitLab/GitHub 배지는 config 탭처럼 그룹 칸에', async () => {
  stub([
    { ...ROWS[0], service: 'shop web', group: 'mall', type: 'web', host: 'gitlab' },
    { ...ROWS[0], service: 'tv2 web', group: 'vault', type: 'web', host: 'github', executor_repo: null, executor_center: null },
  ])
  render(<CicdCompare />)
  const table = within(await screen.findByRole('table'))
  expect(table.getByText('mall').closest('td')).toHaveTextContent(/^mall서비스 1개GitLab$/)
  expect(table.getByText('vault').closest('td')).toHaveTextContent(/^vault서비스 1개GitHub$/)
  expect(table.getByText('shop').closest('td')).toHaveTextContent(/^shop$/) // 서비스 칸엔 배지 없음
  expect(screen.queryByRole('radiogroup', { name: '빌드 필터' })).toBeNull()
})

test('빌드 버전 · 배포 버전 — 환경마다 한 줄, 배포가 빌드보다 옛날이면 빨간 칸, 배포 job 없으면 —, 못 읽으면 모름', async () => {
  const rows: ShapeRow[] = [
    {
      service: 'shop was', group: 'mall', type: 'was', host: 'gitlab',
      deploy: { dev: { path: 'image', manual: false }, prod: { path: 'image', manual: true } },
      versions: {
        build: {
          dev: { version: 'v1.0.9', tag: 'dev-was-v1.0.9', at: '2026-10-12T21:00:00Z', job: 31, side: 'center' },
          prod: { version: 'v1.0.9', tag: 'prod-was-v1.0.9', at: '2026-10-13T10:52:00Z', job: 40, side: 'center' },
          stg: { version: 'v1.0.8', tag: 'stg-was-v1.0.8', at: '2026-10-10T00:00:00Z', job: 20, side: 'center' },
        },
        deploy: {
          dev: { version: 'v1.0.9', tag: 'dev-was-v1.0.9', at: '2026-10-12T21:26:00Z', job: 32, side: 'center' },
          prod: { version: 'v1.0.2', tag: 'prod-was-v1.0.2', at: '2026-10-01T14:23:00Z', job: 30, side: 'center' },
        },
      },
    },
    { service: 'shop web', group: 'mall', type: 'web', host: 'gitlab', deploy: { prod: { path: 'image', manual: false } } }, // 로컬 사본 → 모름
    { service: 'blog web', group: 'blog', type: 'web', host: 'github', deploy: { dev: { path: 'image', by: 'compose', manual: null } } },
  ]
  stub(rows)
  render(<CicdCompare />)
  await screen.findByText('was')
  const table = within(document.querySelector('table.grid--nowrap') as HTMLElement)
  const heads = screen.getAllByRole('columnheader').map((h) => h.textContent)
  expect(heads).toEqual(expect.arrayContaining(['빌드 버전', '배포 버전']))
  const was = table.getByText('was').closest('tr')!
  const cells = [...was.querySelectorAll(':scope > td')]
  const col = (name: string) => cells[heads.indexOf(name) - (heads.length - cells.length)]
  // 빌드: 환경 순서(dev · stg · prod) 로 한 줄씩
  expect([...col('빌드 버전').querySelectorAll('.ver-line')].map((l) => l.textContent)).toEqual(['devv1.0.9', 'stgv1.0.8', 'prodv1.0.9'])
  expect(col('빌드 버전').querySelector('.ver-line')).toHaveAttribute('title', '빌드: dev-was-v1.0.9 · 2026-10-12 · job #31 (center CI)')
  // 배포: prod 는 빌드(v1.0.9)보다 옛날(v1.0.2) → 빨간 칸, stg 는 배포 job 이 없음 → —
  const prod = within(col('배포 버전') as HTMLElement).getByText('⚠ v1.0.2')
  expect(prod).toHaveClass('ver--old')
  expect(prod.closest('.ver-line')).toHaveAttribute('title', expect.stringContaining('빌드는 prod-was-v1.0.9(2026-10-13) — 아직 배포 안 됨'))
  expect(within(col('배포 버전') as HTMLElement).getByText('v1.0.9')).not.toHaveClass('ver--old')
  expect([...col('배포 버전').querySelectorAll('.ver-line')].map((l) => l.textContent)).toEqual(['devv1.0.9', 'stg—', 'prod⚠ v1.0.2'])
  // 버전을 못 읽은 서비스(로컬 사본) = 모름, GitHub = —
  const web = was.previousElementSibling as HTMLElement // 같은 서비스에서 web 이 was 위
  expect(within(web).getAllByText('모름').length).toBe(2)
  const blog = table.getByText('blog', { selector: 'td.svc-cell' }).closest('tr')!
  expect(within(blog).queryByText('모름')).toBeNull() // GitHub 은 아직 못 읽음 → —
  // 요약: 빌드해 두고 배포 안 한 곳 수
  expect(screen.getByText(/배포 안 된 빌드 1곳/)).toBeInTheDocument()
  // 표 읽는 법에 버전 줄
  const legend = screen.getByText('표 읽는 법').closest('details')!
  expect([...legend.querySelectorAll('.legend-grid > dt')].map((d) => d.textContent)).toContain('빌드 버전 · 배포 버전')
})
