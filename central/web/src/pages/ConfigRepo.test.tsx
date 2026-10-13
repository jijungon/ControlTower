import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import ConfigRepo, { missShort } from './ConfigRepo'
import type { ConfigRow } from '../api'

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
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(ROWS), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  render(<ConfigRepo />)
  const table = within(await screen.findByRole('table'))
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
  expect(screen.getByText(/CMD 로 옮기기 1 · 파일 지우기 1 · CMD 넣기 1 · 코드↔이미지 다름 1 · 오래된 버전 \d+칸/)).toBeInTheDocument()
  // 코드에 적힌 버전: 이미지와 다르면 ⚠, '≥' 는 최소 버전이라 이미지가 더 높으면 괜찮음
  const diff = table.getByText('⚠ 다름')
  expect(diff).toHaveAttribute('title', '코드는 node 22(.nvmrc), 이미지는 node 18')
  expect(diff.parentElement).toHaveTextContent(/^node 22⚠ 다름$/) // 한 줄
  expect(diff.parentElement).toHaveAttribute('title', expect.stringContaining('nest 11.0.1')) // nest 는 마우스
  expect(table.getByText('node ≥20')).toBeInTheDocument()
  expect(table.getAllByText('⚠ 다름').length).toBe(1)
  expect(screen.getByText(/출처: center config repo/)).toBeInTheDocument()
  // 서비스별로 묶음: shop 의 6개 폴더가 한 칸
  expect(table.getByText('shop').closest('td')).toHaveAttribute('rowspan', '6')
  // 새로고침 = 다시 불러오기
  await userEvent.click(screen.getByRole('button', { name: 'config 폴더 새로고침' }))
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

test('런타임 필터 — node 18 만 보기', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(ROWS), { status: 200 })))
  render(<ConfigRepo />)
  const table = within(await screen.findByRole('table'))
  await table.findByText('⚠ node 18')
  fireEvent.change(screen.getByLabelText('런타임 필터'), { target: { value: 'node 18' } })
  expect(table.getAllByText('web').length).toBe(1)
  expect(table.queryByText('was')).toBeNull()
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
  const table = within(await screen.findByRole('table'))
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
  await screen.findByRole('table')
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
  const table = within(await screen.findByRole('table'))
  const badge = table.getByText('합쳐짐 → chat/was')
  expect(badge.closest('tr')).toHaveClass('row-merged')
  expect(table.queryByText('CMD 로 옮기기')).toBeNull() // 할 일 대신 '합쳐짐'
  expect(within(badge.closest('tr')!).queryByText('안 읽음')).toBeNull() // 안 쓰는 폴더라 서버 칸은 '—'
  expect(table.getByText('node 18')).not.toHaveClass('ver--old') // 비교에서 빠져서 빨간 칸 아님
  expect(screen.getByText(/CMD 로 옮기기 0 · 파일 지우기 0 · CMD 넣기 0 · 코드↔이미지 다름 0 · 오래된 버전 0칸/)).toBeInTheDocument()
})

test("배포 안 하는 환경은 '안 읽음' 대신 '—', CI 를 못 읽어 모르면 그대로 '안 읽음'", async () => {
  const rows: ConfigRow[] = [
    { path: 'adm/web', runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: [], state: 'done', deploy_envs: ['prod'] },
    { path: 'acc/web', runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: [], state: 'done' },
  ]
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(rows), { status: 200 })))
  render(<ConfigRepo />)
  const table = within(await screen.findByRole('table'))
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
  const table = within(await screen.findByRole('table'))
  const tags = table.getAllByText('(web)', { selector: '.type-roles' })
  expect(tags.length).toBe(2)
  const mgr = tags[0].parentElement!
  expect(mgr).toHaveTextContent(/^manager \(web\)$/)
  expect(mgr).toHaveAttribute('title', expect.stringContaining('config 폴더는 acct/web'))
  expect(table.getByText('acct').closest('td')).toHaveAttribute('rowspan', '2') // 서비스 칸 하나에 두 줄
  expect(screen.getByText(/파일 지우기 1 ·/)).toBeInTheDocument() // 같은 폴더라 한 번
})

test('그룹 칸·그룹 필터 — 빌드·배포 표처럼 그룹 → 서비스 → 타입', async () => {
  const mk = (path: string, group: string): ConfigRow => ({ path, group, runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: [], state: 'done' })
  const rows = [mk('a/web', 'g1'), mk('a/was', 'g1'), mk('b/web', 'g1'), mk('c/web', 'g2')]
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(rows), { status: 200 })))
  render(<ConfigRepo />)
  const table = within(await screen.findByRole('table'))
  const g1 = table.getByText('g1').closest('td')!
  expect(g1).toHaveClass('grp-cell')
  expect(g1).toHaveAttribute('rowspan', '3')
  expect(g1).toHaveTextContent('서비스 2개')
  expect(g1.closest('tr')).toHaveClass('grp-start')
  fireEvent.change(screen.getByLabelText('그룹 필터'), { target: { value: 'g2' } })
  expect(table.queryByText('g1')).toBeNull()
  expect(table.getByText('c')).toBeInTheDocument()
})
