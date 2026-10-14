import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import ConfigRepo, { missShort } from './ConfigRepo'
import type { ConfigRow } from '../api'
import { findDataTable } from '../test/dataTable'

const ROWS: ConfigRow[] = [
  { path: 'shop/web', runtime: 'node', runtime_version: '18', base_image: 'infra/nodejs', base_tag: 'v18', start: 'start.sh', start_files: ['node-startup.sh'], state: 'legacy', compose: { prod: 'mount', dev: 'command' }, collected_at: '2026-10-13T03:00:00+00:00',
    compose_src: { dev: { kind: 'ssh', auto: true, via: 'gw-dev', where: 'gw-dev → 10.0.0.1:/app/web-shop/docker-compose.yml' }, prod: { kind: 'file', note: '옛 사본', where: 'old/prod.yml' } },
    code: { node: '22', node_from: '.nvmrc', node_rule: 'exact', nest: '11.0.1' } }, // 코드 22 ≠ 이미지 18 → ⚠
  { path: 'shop/admin', runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: ['node-startup.sh'], state: 'leftover',
    code: { node: '20', node_from: 'package.json', node_rule: 'min' } }, // ≥20 이고 이미지 22 → 괜찮음
  { path: 'shop/api', runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: [], state: 'done', compose: { prod: 'image' },
    compose_miss: {
      stg: { state: 'fail', reason: '~/.ssh/config 에 직접 등록 안 된 서버 — 게이트웨이를 거쳐야 할 수 있음 — /app/api/docker-compose.yml' },
    } },
  { path: 'shop/was', runtime: 'java', runtime_version: '17', base_image: 'infra/springboot', base_tag: '0.1.3-java17', start: 'base', start_files: [], state: 'base' },
  { path: 'shop/empty', state: 'none' },
  { path: 'shop/job', runtime: 'node', runtime_version: '22', base_image: 'infra/nodejs', base_tag: 'v22', start: 'server', start_files: ['node-startup.sh'], state: 'server', compose: { dev: 'command' } },
]

test('처음 실행할 명령(이미지·서버)·정리할 것 — 한 가지 말로 + 오래된 버전 빨간 칸', async () => {
  const fetchMock = vi.fn(async (_url: string) => new Response(JSON.stringify(ROWS), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  render(<ConfigRepo />)
  const table = within(await findDataTable())
  expect(table.getByText('⚠ node 18')).toHaveClass('ver--old') // 최신 22
  expect(table.getAllByText('node 22')[0]).not.toHaveClass('ver--old')
  // 머리줄: 칸 이름이 모두 '처음 실행할 명령' 하나의 말
  const heads = screen.getAllByRole('columnheader').map((h) => h.textContent)
  for (const h of ['처음 실행할 명령 (이미지)', '처음 실행할 명령 (서버)', '정리할 것', 'dev', 'prod'])
    expect(heads.some((x) => x?.startsWith(h))).toBe(true)
  expect(heads).not.toContain('start.sh 파일')
  // (이미지): start.sh / Dockerfile CMD / 베이스 기본값 / 없음 → 서버가 줌
  expect(table.getAllByText('start.sh', { selector: '.badge' })[0]).toHaveClass('badge--warn')
  expect(table.getAllByText('Dockerfile CMD', { selector: '.badge' }).length).toBe(2)
  expect(table.getByText('베이스 이미지', { selector: '.badge' })).toBeInTheDocument()
  // java(베이스 이미지가 jar 실행)는 start.sh 를 안 쓰니 정리할 것에 '없음' 대신 이유를 적음(회색)
  const javaRow = table.getByText('java 17').closest('tr')!
  expect(within(javaRow).getByText('java 라 start.sh 안 씀', { selector: '.badge' })).toHaveClass('badge--muted')
  // 그래서 서버 칸도 '안 읽음'(할 일) 대신 '—'(읽을 필요 없음)
  expect(within(javaRow).queryByText('안 읽음')).toBeNull()
  // 맨 위 묶음 머리: 버전 / start.sh
  expect(screen.getByRole('columnheader', { name: /^버전$/ })).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: /start\.sh — 앱을 처음 띄우는 명령은 어디에\?/ })).toBeInTheDocument()
  expect(table.getByText('없음 → 서버가 줌')).toBeInTheDocument()
  // (서버): dev·stg·prod 열로 나뉨 — 읽었거나 읽으려 한 환경만. compose 가 명령을 주면 '서버 compose', start.sh 마운트면 'start.sh'
  expect(heads).toContain('stg') // dev·stg·prod 는 항상
  expect(heads).not.toContain('기타') // lab·preview 데이터가 없으면 '기타' 열도 없음
  const webRow = table.getByText('CMD 로 옮기기').closest('tr')!
  const cells = [...webRow.querySelectorAll('td')].map((td) => td.textContent)
  // ● = 실제로 실행되는 명령: dev 는 compose 가 덮어씀, prod 는 start.sh 를 넣음 → 둘 다 서버 칸에 ●
  // 칸은 한 줄 — 어디서 읽었나는 같은 줄 끝의 작은 글씨
  expect(cells).toContain('서버 composegw') // dev: 게이트웨이를 거쳐 실서버에서 읽음
  expect(cells).toContain('start.sh옛 사본') // prod: 옛 하네스 파일
  expect(webRow.querySelectorAll('.cell-sub').length).toBe(0) // 두 번째 줄 없음
  expect(webRow.querySelectorAll('.run-dot').length).toBe(2)
  // (이미지) 칸: 읽은 서버가 모두 덮어써서 흐린 배지(서버에선 안 씀 — 마우스)
  expect(webRow.querySelector('.run-unused')).toHaveAttribute('title', expect.stringContaining('서버에선 안 씀'))
  expect(table.getAllByText('서버 compose').length).toBe(2) // shop/web dev + shop/job dev
  // 정리할 것
  expect(table.getByText('CMD 로 옮기기')).toHaveClass('badge--danger')
  expect(table.getByText('start.sh 지우기')).toHaveAttribute('title', expect.stringContaining('node-startup.sh'))
  // 이미지 그대로 쓰는 서버: 서버 칸은 '← 이미지', (이미지) 칸에 ● (어디서 실행되나는 마우스)
  const apiRow = table.getByText('← 이미지').closest('tr')!
  expect(apiRow).toHaveTextContent('← 이미지')
  expect(apiRow).toHaveTextContent('안 읽음') // dev: 아직 읽으려고 하지 않음
  // stg: 읽으려 했는데 실패 → '못 읽음' + 짧은 이유, 마우스를 올리면 전체 이유
  const fail = within(apiRow).getByText('못 읽음')
  expect(fail).toHaveClass('st-fail') // 빨간 알약
  expect(fail.parentElement).toHaveTextContent('못 읽음직접 접속 안 됨')
  // 상태마다 모양이 다름: ← 이미지(초록) · 안 읽음(점선)
  expect(within(apiRow).getByText('← 이미지')).toHaveClass('st-asis')
  expect(within(apiRow).getByText('안 읽음')).toHaveClass('st-unread')
  expect(fail.parentElement).toHaveAttribute('title', expect.stringContaining('/app/api/docker-compose.yml'))
  expect(within(apiRow).getByText('Dockerfile CMD').parentElement).toHaveAttribute('title', '이 명령을 그대로 실행하는 서버: prod')
  expect(apiRow.querySelectorAll('.run-dot').length).toBe(1)
  expect(table.getByText('CMD 넣기')).toBeInTheDocument()
  expect(table.getByText('Dockerfile 없음')).toBeInTheDocument()
  expect(screen.getByText(/할 일 — CMD 로 옮기기 1 · start\.sh 지우기 1 · CMD 넣기 1 · 오래된 버전 \d+칸/)).toBeInTheDocument()
  // 코드에 적힌 버전은 repo 에서 읽는 값 → repo 보기로 옮김(center 표엔 없음)
  expect(heads.some((h) => h?.startsWith('코드에 적힌 버전'))).toBe(false)
  expect(table.queryByText('⚠ 다름')).toBeNull()
  // 표 읽는 법: 기본은 접힘, '칸 | 뜻' 표 + 맨 아래 출처
  const legend = screen.getByText('표 읽는 법').closest('details')!
  expect(legend).not.toHaveAttribute('open')
  expect(within(legend).getByText('출처').nextElementSibling).toHaveTextContent(/^center config repo · 서버 docker-compose/)
  expect([...legend.querySelectorAll('.legend-grid > dt')].map((d) => d.textContent)).toEqual(['버전', '처음 실행할 명령', '(이미지) 칸', '(서버) 칸', '정리할 것', '출처'])
  // 칸마다 '무엇을 보여주나' 한 줄 + '값 → 뜻' 목록(값마다 한 줄)
  const todo = [...legend.querySelectorAll('.legend-grid > dt')].find((d) => d.textContent === '정리할 것')!.nextElementSibling!
  expect(todo.querySelector('.legend-what')).toHaveTextContent('다음에 할 일')
  expect([...todo.querySelectorAll('.legend-items .legend-v')].map((d) => d.textContent)).toEqual(['CMD 로 옮기기', 'start.sh 지우기', 'CMD 넣기', '없음', 'java 라 start.sh 안 씀', '합쳐짐 → chat/was'])
  // 서비스별로 묶음: shop 의 6개 폴더가 한 칸
  expect(table.getByText('shop').closest('td')).toHaveAttribute('rowspan', '6')
  // 새로고침 = 다시 불러오기
  await userEvent.click(screen.getByRole('button', { name: 'config 폴더 새로고침' }))
  expect(fetchMock.mock.calls.filter(([u]) => String(u).includes('/api/cicd/config')).length).toBe(2)
})

test('빈 상태 안내', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })))
  render(<ConfigRepo />)
  expect(await screen.findByText(/아직 config 를 읽지 않았습니다/)).toBeInTheDocument()
  expect(screen.getByText('아직 수집 없음')).toBeInTheDocument()
})

test("lab·preview 는 '기타' 한 열에 모음", async () => {
  const rows: ConfigRow[] = [
    { path: 'shop/web', runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: [], state: 'done',
      compose: { dev: 'image', lab: 'command' }, compose_miss: { preview: { state: 'fail', reason: 'SSH 설정에 없는 서버' } } },
  ]
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(rows), { status: 200 })))
  render(<ConfigRepo />)
  const table = within(await findDataTable())
  expect(screen.getByRole('columnheader', { name: '기타' })).toBeInTheDocument()
  // 한 줄에 이어서: 'lab ● 서버 compose · preview 못 읽음'
  const lines = [...document.querySelectorAll('.extra-line')]
  expect(lines.map((l) => l.textContent)).toEqual(['lab ● 서버 compose', 'preview 못 읽음'])
  expect(lines[1]).toHaveClass('miss-fail')
  expect(lines[0]).not.toHaveClass('st-unread-text')
  expect(lines[0].closest('td')).toHaveTextContent('lab ● 서버 compose · preview 못 읽음')
  cleanup()
  // 결과가 같은 환경은 하나로 묶음
  const same: ConfigRow[] = [{ ...rows[0], compose: { lab: 'mount', preview: 'mount' }, compose_miss: {} }]
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(same), { status: 200 })))
  render(<ConfigRepo />)
  await findDataTable()
  expect([...document.querySelectorAll('.extra-line')].map((l) => l.textContent)).toEqual(['lab·preview ● start.sh'])
})

test('못 읽음 이유를 짧게', () => {
  expect(missShort('SSH 로 못 읽음 — gw → x (Host key verification failed.)')).toBe('서버 지문 모름')
  expect(missShort('SSH 로 못 읽음 — gw → x (ubuntu@x: Permission denied (publickey).)')).toBe('권한 없음')
  expect(missShort('SSH 로 못 읽음 — gw → x (ssh: connect to host x port 22: Connection timed out)')).toBe('네트워크 안 닿음')
  expect(missShort('SSH 로 못 읽음 — gw → x (cat: /app/x: No such file or directory)')).toBe('파일 없음')
  expect(missShort('SSH 로 못 읽음 — gw(sudo) → x (sudo: a password is required)')).toBe('sudo 안 됨')
})

test('합쳐진 폴더는 흐리게 + 합쳐짐 → 합쳐진 곳, 요약에서 빠짐', async () => {
  const rows: ConfigRow[] = [
    { path: 'chat/was', runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: [], state: 'done' },
    { path: 'cm/was', runtime: 'node', runtime_version: '18', base_image: 'node', base_tag: '18-slim', start: 'start.sh', start_files: ['start.sh'], state: 'legacy', merged_into: 'chat/was' },
  ]
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(rows), { status: 200 })))
  render(<ConfigRepo />)
  const table = within(await findDataTable())
  const badge = table.getByText('합쳐짐 → chat/was')
  expect(badge.closest('tr')).toHaveClass('row-merged')
  expect(table.queryByText('CMD 로 옮기기')).toBeNull() // 할 일 대신 '합쳐짐'
  expect(within(badge.closest('tr')!).queryByText('안 읽음')).toBeNull() // 안 쓰는 폴더라 서버 칸은 '—'
  expect(table.getByText('node 18')).not.toHaveClass('ver--old') // 비교에서 빠져서 빨간 칸 아님
  expect(screen.getByText(/CMD 로 옮기기 0 · start\.sh 지우기 0 · CMD 넣기 0 · 오래된 버전 0칸/)).toBeInTheDocument()
})

test("배포 안 하는 환경은 '안 읽음' 대신 '—', CI 를 못 읽어 모르면 그대로 '안 읽음'", async () => {
  const rows: ConfigRow[] = [
    { path: 'adm/web', runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: [], state: 'done', deploy_envs: ['prod'] },
    { path: 'acc/web', runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: [], state: 'done' },
  ]
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(rows), { status: 200 })))
  render(<ConfigRepo />)
  const table = within(await findDataTable())
  const adm = table.getByText('adm').closest('tr')!
  expect(within(adm).getAllByText('—', { selector: 'span' }).map((e) => e.getAttribute('title'))).toEqual(
    expect.arrayContaining([expect.stringContaining('dev 에 배포 안 함'), expect.stringContaining('stg 에 배포 안 함')]),
  )
  expect(within(adm).getAllByText('안 읽음').length).toBe(1) // prod 만 — 배포하는 곳인데 아직 안 읽음
  const acc = table.getByText('acc').closest('tr')!
  expect(within(acc).getAllByText('안 읽음').length).toBe(3) // 어디 배포하는지 모름 → 셋 다 '안 읽음'
})

test('역할로 나뉜 폴더는 역할마다 한 줄 + 옆에 실제 폴더, 요약 숫자는 폴더 기준 한 번', async () => {
  const base: Omit<ConfigRow, 'path'> = { runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: ['node-startup.sh'], state: 'leftover' }
  const rows: ConfigRow[] = [
    { ...base, path: 'acct/manager', folder: 'acct/web', compose: { prod: 'command' } },
    { ...base, path: 'acct/syncer', folder: 'acct/web', compose: { prod: 'command' } },
  ]
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(rows), { status: 200 })))
  render(<ConfigRepo />)
  const table = within(await findDataTable())
  const tags = table.getAllByText('(web)', { selector: '.type-roles' })
  expect(tags.length).toBe(2)
  const mgr = tags[0].parentElement!
  expect(mgr).toHaveTextContent(/^manager \(web\)$/)
  expect(mgr).toHaveAttribute('title', expect.stringContaining('config 폴더는 acct/web'))
  expect(table.getByText('acct').closest('td')).toHaveAttribute('rowspan', '2') // 서비스 칸 하나에 두 줄
  expect(screen.getByText(/start\.sh 지우기 1 ·/)).toBeInTheDocument() // 같은 폴더라 한 번
})

test('그룹 칸·그룹 필터 — 빌드·배포 표처럼 그룹 → 서비스 → 타입, 런타임 필터는 없음', async () => {
  const mk = (path: string, group: string): ConfigRow => ({ path, group, runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: [], state: 'done' })
  const rows = [mk('a/web', 'g1'), mk('a/was', 'g1'), mk('b/web', 'g1'), mk('c/web', 'g2')]
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(rows), { status: 200 })))
  render(<ConfigRepo />)
  const table = within(await findDataTable())
  const g1 = table.getByText('g1').closest('td')!
  expect(g1).toHaveClass('grp-cell')
  expect(g1).toHaveAttribute('rowspan', '3')
  expect(g1).toHaveTextContent('서비스 2개')
  expect(g1.closest('tr')).toHaveClass('grp-start')
  const seg = screen.getByRole('radiogroup', { name: '그룹 필터' }) // 빌드·배포 탭과 같은 알약 버튼
  expect(within(seg).getByRole('radio', { name: '전체' })).toHaveAttribute('aria-checked', 'true')
  fireEvent.click(within(seg).getByRole('radio', { name: 'g2' }))
  expect(within(seg).getByRole('radio', { name: 'g2' })).toHaveAttribute('aria-checked', 'true')
  expect(table.queryByText('g1')).toBeNull()
  expect(screen.queryByLabelText('런타임 필터')).toBeNull()
  expect(table.getByText('c')).toBeInTheDocument()
})

test('줄마다 ▸ 펼치면 환경 | 처음 실행할 명령 | 어디서 읽었나 | 위치·이유 표', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(ROWS), { status: 200 })))
  render(<ConfigRepo />)
  const table = within(await findDataTable())
  const toggle = screen.getByRole('button', { name: 'shop/web 환경별 자세히' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  const mini = document.querySelector('tr.row-detail table.mini-table')!
  expect([...mini.querySelectorAll('th')].map((th) => th.textContent)).toEqual(['환경', '처음 실행할 명령', '어디서 읽었나', '위치 · 이유'])
  const rows = [...mini.querySelectorAll(':scope > tbody > tr')].map((tr) => [...tr.querySelectorAll('td')].map((td) => td.textContent).join(' | '))
  expect(rows).toEqual([
    '(이미지) | start.sh | config repo | shop/web/',
    'dev | 서버 compose — compose 가 덮어씀 | gw | gw-dev → 10.0.0.1:/app/web-shop/docker-compose.yml',
    'stg | 안 읽음 | — | 아직 서버를 안 봄',
    'prod | start.sh — start.sh 넣음 | 옛 사본 | old/prod.yml',
  ])
  // 서비스 칸이 펼친 줄만큼 길어짐(rowspan 6 → 7)
  expect(table.getByText('shop').closest('td')).toHaveAttribute('rowspan', '7')
  fireEvent.click(toggle)
  expect(document.querySelector('tr.row-detail')).toBeNull()
})

test('그룹 칸에 config repo(GitLab), GitHub 서비스는 표 아래 안내', async () => {
  const cfg: ConfigRow[] = [{ path: 'shop/web', group: 'g1', config_repo: 'shop/config', runtime: 'node', runtime_version: '22', start: 'dockerfile', start_files: [], state: 'done' }]
  const shapes = [{ service: 'tv2 web', host: 'github' }, { service: 'shop web', host: 'gitlab' }]
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.includes('/api/cicd/shape') ? shapes : cfg), { status: 200 })))
  render(<ConfigRepo />)
  const table = within(await findDataTable())
  expect(table.getByText('g1').closest('td')).toHaveTextContent('shop/configGitLab')
  expect(await screen.findByText(/에서 빌드하는 서비스는 GitLab config repo 를 안 써서 이 표에 없어요 — tv2 web/)).toBeInTheDocument()
})

beforeEach(() => localStorage.setItem('ct.config.side', 'center')) // 아래 대부분은 center 보기 테스트(기본은 repo)
afterEach(() => localStorage.clear()) // 고른 보기(center/repo)는 브라우저에 기억 → 테스트마다 비움

test('repo 보기 — 서비스마다 repo 프로젝트 · 빌드(CI 이미지) · 코드 · 실행(center 이미지) + 다른 것 표시, 고른 보기 기억', async () => {
  const cfg: ConfigRow[] = [{ path: 'shop/web', group: 'g1', runtime: 'node', runtime_version: '22', start: 'dockerfile', start_files: [], state: 'done' }]
  const shapes = [
    { service: 'shop web', group: 'g1', type: 'web', host: 'gitlab', runtime: 'node', runtime_version: '22',
      repo: { project: 'team/apps/shop-web', read: true, build: [{ runtime: 'node', version: '20', image: 'node:20-slim', jobs: ['build', 'test'] }],
        code: { node: '22', node_from: '.nvmrc', node_rule: 'exact', nest: '10.3.0' } } },
    { service: 'shop was', group: 'g1', type: 'was', host: 'gitlab', runtime: 'node', runtime_version: '22',
      repo: { project: 'team/apps/shop-was', read: true, build: [{ runtime: 'node', version: '22', image: 'node:22', jobs: ['build'] }], code: { node: '20', node_from: 'package.json', node_rule: 'min' } } },
    { service: 'pay', group: 'g1', type: 'was', host: 'gitlab', repo: { project: 'team/pay', read: false, build: [] } },
    // 같은 repo 하나를 두 역할이 씀 → repo 프로젝트 칸 하나로 합침
    { service: 'acct manager', group: 'g1', type: 'manager', host: 'gitlab', runtime: 'node', runtime_version: '22', repo: { project: 'team/acct', read: true, build: [], code: {} } },
    { service: 'acct syncer', group: 'g1', type: 'syncer', host: 'gitlab', runtime: 'node', runtime_version: '22', repo: { project: 'team/acct', read: true, build: [], code: {} } },
    // 코드에 버전이 없고 빌드(20) ≠ 실행(22) → 실행을 기준으로 빌드가 빨간 칸
    { service: 'bot', group: 'g1', type: 'bot', host: 'gitlab', runtime: 'node', runtime_version: '22',
      repo: { project: 'team/bot', read: true, build: [{ runtime: 'node', version: '20', image: 'node:20', jobs: ['build'] }], code: {} } },
    // shell 러너 빌드 — job 로그에서 읽은 node 20.15.1, 실행은 node 18 → 빨간 칸 / 같은 러너 값으로 추정
    { service: 'site', group: 'g1', type: 'web', host: 'gitlab', runtime: 'node', runtime_version: '18',
      repo: { project: 'team/site', read: true, code: {}, build: [{ runtime: 'node', version: '20.15.1', image: null, jobs: ['build'], from: 'log', job: 31, runner: 'shell-01' }] } },
    { service: 'front', group: 'g1', type: 'web', host: 'gitlab', runtime: 'node', runtime_version: '20',
      repo: { project: 'team/front', read: true, code: {}, build: [{ runtime: 'node', version: '20.15.1', image: null, jobs: ['build'], from: 'log', job: 31, runner: 'shell-01', guess: true }] } },
    // shell 러너로 빌드(이미지 없음) · Gradle 에 java 17
    { service: 'pnl', group: 'g1', type: 'was', host: 'gitlab', runtime: 'java', runtime_version: '17',
      executor_repo: { value: 'shell', guess: false, groups: [{ tag: 'shell-runner', value: 'shell', guess: false, jobs: ['build'] }] },
      repo: { project: 'team/pnl', read: true, build: [], code: { java: '17', java_from: 'build.gradle' } } },
    { service: 'sync', group: 'g1', type: 'was', host: 'gitlab', repo: null }, // repo 를 안 적음
    { service: 'tv2 web', group: 'g2', type: 'web', host: 'github' },
  ]
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.includes('/api/cicd/shape') ? shapes : cfg), { status: 200 })))
  localStorage.clear() // 처음 여는 사람 = 기본 보기
  const { unmount } = render(<ConfigRepo />)
  await findDataTable()
  // 보기 순서는 흐름대로 repo → center, 처음엔 repo
  expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['repo', 'center'])
  expect(screen.getByRole('tab', { name: 'repo' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByText('repo 가 무엇으로 빌드하나 — 서비스마다')).toBeInTheDocument()
  const table = within(screen.getByRole('table'))
  const heads = screen.getAllByRole('columnheader').map((h) => h.textContent)
  for (const h of ['repo 프로젝트', '빌드 (repo CI 이미지)', '코드에 적힌 버전', '실행 (center 이미지)', '확인할 것']) expect(heads).toContain(h)
  expect(heads.indexOf('repo 프로젝트')).toBeLessThan(heads.indexOf('타입')) // repo 프로젝트 → 타입
  // shop web: 빌드 node 20 · 코드 node 22 · 실행 node 22 → 빌드≠코드, 빌드≠실행
  const web = table.getByTitle('repo 프로젝트: team/apps/shop-web (GitLab)').closest('tr')!
  expect(table.getByTitle('repo 프로젝트: team/apps/shop-web (GitLab)').querySelectorAll('.grp-repo-part').length).toBe(3) // '/' 에서만 줄바꿈
  const acct = table.getByTitle('repo 프로젝트: team/acct (GitLab)')
  expect(table.getAllByTitle('repo 프로젝트: team/acct (GitLab)').length).toBe(1)
  expect(acct.closest('td')).toHaveAttribute('rowspan', '2')
  // 기준(코드 node 22)과 다른 빌드는 빨간 칸, 같은 실행은 그대로
  const build = within(web).getByText('⚠ node 20')
  expect(build).toHaveClass('ver--old')
  expect(build).toHaveAttribute('title', '코드(node 22, .nvmrc)와 다름\nCI 이미지 node:20-slim · job build, test')
  expect(within(web).getByText('node 22', { selector: '[title="center config 의 Dockerfile FROM"]' })).not.toHaveClass('ver--old')
  expect(within(web).getByText('node 22', { selector: '[title^="출처"]' })).toHaveAttribute('title', '출처: .nvmrc · nest 10.3.0')
  expect([...web.querySelectorAll('.badge--warn')].map((b) => b.textContent)).toEqual(['⚠ 빌드≠코드', '⚠ 빌드≠실행'])
  expect(within(web).getByText('⚠ 빌드≠코드')).toHaveAttribute('title', '빌드는 node 20(CI 이미지 node:20-slim), 코드는 node 22(.nvmrc)')
  // shop was: 코드는 '≥20'(최소) 이고 빌드·실행 22 → 괜찮음
  const was = table.getByTitle('repo 프로젝트: team/apps/shop-was (GitLab)').closest('tr')!
  expect(within(was).getByText('node ≥20')).toBeInTheDocument()
  expect(within(was).getByText('없음', { selector: '.badge--ok' })).toBeInTheDocument()
  // repo CI 를 못 읽은 서비스 · repo 를 안 적은 서비스 · GitHub 서비스
  expect(within(table.getByTitle('repo 프로젝트: team/pay (GitLab)').closest('tr')!).getByText('못 읽음')).toBeInTheDocument()
  expect(screen.getByText(/repo 프로젝트를 안 적은 서비스 — sync/)).toBeInTheDocument()
  expect(screen.getByText(/에서 빌드하는 서비스는 GitLab repo 가 없어 이 표에 없어요 — tv2 web/)).toBeInTheDocument()
  expect(table.queryByText('tv2')).toBeNull()
  expect(screen.getByText('확인할 것 — 빌드≠코드 1 · 빌드≠실행 3 · 코드≠실행 0')).toBeInTheDocument()
  // job 로그에서 읽은 빌드 — (로그) 표시, 실행(node 18)과 다르면 빨간 칸 / 같은 러너 값은 (추정)
  const site = table.getByTitle('repo 프로젝트: team/site (GitLab)').closest('tr')!
  const siteBuild = within(site).getByText('⚠ node 20.15.1')
  expect(siteBuild).toHaveAttribute('title', expect.stringContaining('job 로그 #31 (build) — CI 에 이미지가 없어 shell 러너(shell-01)'))
  expect(siteBuild.parentElement).toHaveTextContent('(로그)')
  expect(within(site).getByText('⚠ 빌드≠실행')).toHaveAttribute('title', '빌드는 node 20.15.1(job 로그), 실행 이미지는 node 18')
  const front = table.getByTitle('repo 프로젝트: team/front (GitLab)').closest('tr')!
  expect(within(front).getByText('node 20.15.1')).toHaveAttribute('title', expect.stringContaining('같은 러너(shell-01)의 다른 job 로그 #31'))
  expect(within(front).getByText('node 20.15.1').parentElement).toHaveTextContent('(추정)')
  // 코드에 버전이 없으면 실행이 기준
  const bot = table.getByTitle('repo 프로젝트: team/bot (GitLab)').closest('tr')!
  expect(within(bot).getByText('⚠ node 20')).toHaveAttribute('title', expect.stringMatching(/^실행 이미지\(node 22\)와 다름/))
  expect(within(bot).getByText('안 적힘')).toBeInTheDocument() // '—' 대신 이유
  // shell 러너 빌드 = CI 에 없음 (shell), Gradle java 는 출처 build.gradle
  const pnl = table.getByTitle('repo 프로젝트: team/pnl (GitLab)').closest('tr')!
  expect(within(pnl).getByText('CI 에 없음 (shell)')).toHaveAttribute('title', expect.stringContaining('shell 러너 서버'))
  expect(within(pnl).getByText('java 17', { selector: '[title^="출처"]' })).toHaveAttribute('title', '출처: build.gradle')
  // 고른 보기는 기억 — center 로 바꾸고 다시 열면 center 그대로
  await userEvent.click(screen.getByRole('tab', { name: 'center' }))
  unmount()
  render(<ConfigRepo />)
  expect(await screen.findByRole('tab', { name: 'center' })).toHaveAttribute('aria-selected', 'true')
})
