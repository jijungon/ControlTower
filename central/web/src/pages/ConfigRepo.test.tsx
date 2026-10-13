import { fireEvent, render, screen, within } from '@testing-library/react'
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
  expect(heads).toEqual(expect.arrayContaining(['처음 실행할 명령 (이미지)', '처음 실행할 명령 (서버)', '정리할 것', 'dev', 'prod']))
  expect(heads).not.toContain('start.sh 파일')
  // (이미지): start.sh / Dockerfile CMD / 베이스 기본값 / 없음 → 서버가 줌
  expect(table.getAllByText('start.sh', { selector: '.badge' })[0]).toHaveClass('badge--warn')
  expect(table.getAllByText('Dockerfile CMD', { selector: '.badge' }).length).toBe(2)
  expect(table.getByText('베이스 기본값')).toBeInTheDocument()
  expect(table.getByText('없음 → 서버가 줌')).toBeInTheDocument()
  // (서버): dev·stg·prod 열로 나뉨 — 읽었거나 읽으려 한 환경만. compose 가 명령을 주면 '서버 compose', start.sh 마운트면 'start.sh'
  expect(heads).toContain('stg') // dev·stg·prod 는 항상
  expect(heads).not.toContain('기타') // lab·preview 데이터가 없으면 '기타' 열도 없음
  const webRow = table.getByText('CMD 로 옮기기').closest('tr')!
  const cells = [...webRow.querySelectorAll('td')].map((td) => td.textContent)
  // ● = 실제로 실행되는 명령: dev 는 compose 가 덮어씀, prod 는 start.sh 를 넣음 → 둘 다 서버 칸에 ●
  expect(cells).toContain('서버 compose덮어씀 · gw 경유') // dev: 게이트웨이를 거쳐 실서버에서 읽음
  expect(cells).toContain('start.sh넣음 · 옛 사본') // prod: 옛 하네스 파일
  expect(webRow.querySelectorAll('.run-dot').length).toBe(2)
  // (이미지) 칸: 읽은 서버가 모두 덮어써서 '서버에선 안 씀'
  expect(cells).toContain('start.sh서버에선 안 씀')
  expect(table.getAllByText('서버 compose').length).toBe(2) // shop/web dev + shop/job dev
  // 정리할 것
  expect(table.getByText('CMD 로 옮기기')).toHaveClass('badge--danger')
  expect(table.getByText('start.sh 지우기')).toHaveAttribute('title', expect.stringContaining('node-startup.sh'))
  // 이미지 그대로 쓰는 서버: 서버 칸은 '← 이미지', (이미지) 칸에 '● 실행: prod'
  const apiRow = table.getByText('없음', { selector: '.badge' }).closest('tr')!
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
  expect(apiRow).toHaveTextContent('Dockerfile CMD실행: prod')
  expect(apiRow.querySelectorAll('.run-dot').length).toBe(1)
  expect(table.getByText('CMD 넣기')).toBeInTheDocument()
  expect(table.getByText('Dockerfile 없음')).toBeInTheDocument()
  expect(screen.getByText(/CMD 로 옮기기 1 · 파일 지우기 1 · CMD 넣기 1 · 코드↔이미지 다름 1 · 오래된 버전 \d+칸/)).toBeInTheDocument()
  // 코드에 적힌 버전: 이미지와 다르면 ⚠, '≥' 는 최소 버전이라 이미지가 더 높으면 괜찮음
  const diff = table.getByText('⚠ 이미지와 다름')
  expect(diff).toHaveAttribute('title', '코드는 node 22(.nvmrc), 이미지는 node 18')
  expect(diff.parentElement).toHaveTextContent(/^node 22⚠ 이미지와 다름nest 11\.0\.1$/)
  expect(table.getByText('node ≥20')).toBeInTheDocument()
  expect(table.getAllByText('⚠ 이미지와 다름').length).toBe(1)
  expect(table.getByText('nest 11.0.1')).toBeInTheDocument()
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
  expect(table.getByText('lab ● 서버 compose')).toBeInTheDocument()
  expect(table.getByText('preview 못 읽음')).toHaveClass('miss-fail')
  expect(table.getByText('lab ● 서버 compose')).not.toHaveClass('st-unread-text')
})

test('못 읽음 이유를 짧게', () => {
  expect(missShort('SSH 로 못 읽음 — gw → x (Host key verification failed.)')).toBe('서버 지문 모름')
  expect(missShort('SSH 로 못 읽음 — gw → x (ubuntu@x: Permission denied (publickey).)')).toBe('권한 없음')
  expect(missShort('SSH 로 못 읽음 — gw → x (ssh: connect to host x port 22: Connection timed out)')).toBe('네트워크 안 닿음')
  expect(missShort('SSH 로 못 읽음 — gw → x (cat: /app/x: No such file or directory)')).toBe('파일 없음')
})
