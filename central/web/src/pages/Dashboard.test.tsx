import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Dashboard from './Dashboard'

const SERVERS = [
  { id: 1, hostname: 'web-01', ssh_user: 'deploy', status: 'online', last_checked_at: '2026-09-14T00:00:00+00:00' },
  { id: 2, hostname: 'web-02', ssh_user: 'deploy', status: 'unknown' },
]
const CONF = [
  { server_id: 1, hostname: 'web-01', path: '/etc/nginx/nginx.conf', status: 'synced' },
  { server_id: 2, hostname: 'web-02', path: '/etc/nginx/nginx.conf', status: 'drift' },
]
const UPDATES = [
  { server_id: 1, hostname: 'web-01', pending: 2, security: 1, packages: [] },
  { server_id: 2, hostname: 'web-02', pending: 1, security: 0, packages: [] },
]
const VERSIONS = [
  { kind: 'server', name: 'old-01', tools: { node: '10.24.0', python: '3.6.8' } }, // EOL
  { kind: 'server', name: 'new-01', tools: { node: '20.11.1', python: '3.10.12' } }, // OK — 3.10 은 EOL 아님(3.1 오독 방지)
]

const SHAPES = [
  { service: 'shop web', type: 'web', collected_at: '2026-09-15T00:00:00+00:00',
    deploy: { dev: { path: 'direct', by: 'repo', manual: false }, stg: { path: 'direct', by: 'center', manual: false }, prod: { path: 'image', manual: true, mismatch: true } },
    executor_center: { value: 'shell', guess: true, groups: [{ tag: 'b', value: 'shell', guess: true, jobs: ['build'] }] } },
]
const CONFIG = [
  { path: 'shop/web', runtime: 'node', runtime_version: '18', base_image: 'node', base_tag: '18-slim', state: 'legacy', start: 'start.sh',
    code: { node: '22', node_from: '.nvmrc', node_rule: 'exact' }, compose_miss: { prod: { state: 'fail', reason: 'x' } } },
  { path: 'shop/api', runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', state: 'leftover', start: 'dockerfile' },
  { path: 'old/was', state: 'legacy', merged_into: 'shop/api' }, // 합쳐진 폴더는 셈에서 빠짐
]

function routedFetch(url: string) {
  const body = url.includes('/api/cicd/shape')
    ? SHAPES
    : url.includes('/api/cicd/config')
      ? CONFIG
      : url.includes('/api/servers')
    ? SERVERS
    : url.includes('/api/updates')
      ? UPDATES
      : url.includes('/api/versions')
        ? VERSIONS
        : url.includes('/api/conf')
          ? CONF
          : []
  return new Response(JSON.stringify(body), { status: 200 })
}

test('탭마다 요약 카드 + 먼저 볼 것 + 수집 현황, 카드를 누르면 그 탭으로', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => routedFetch(url)))
  const go = vi.fn()
  render(<Dashboard onGo={go} />)
  expect(await screen.findByText('1/2')).toBeInTheDocument() // 온라인 1/2
  const card = (label: string) => screen.getByText(label, { selector: '.label' }).closest('a')!
  expect(card('보안 패치')).toHaveTextContent('보안 패치대기 3') // 대기 2+1
  // 빌드·배포: 파일 복사로 배포하는 곳 2(repo 직배포 1), config: 할 일 2(옮기기 1·지우기 1), 오래된 버전(node 18) · 코드≠이미지 1
  expect(card('파일 복사 배포')).toHaveTextContent(/^빌드·배포2파일 복사 배포이미지로 옮길 곳 · repo 직배포 1$/)
  expect(card('start.sh 할 일')).toHaveTextContent(/^config2start\.sh 할 일CMD 로 옮기기 1 · 지우기 1 · CMD 넣기 0$/)
  expect(card('start.sh 할 일')).toHaveClass('stat--danger')
  expect(card('오래된 버전')).toHaveTextContent('코드≠이미지 1')
  fireEvent.click(card('파일 복사 배포'))
  expect(go).toHaveBeenCalledWith('빌드·배포')
  // 먼저 볼 것: CMD 로 옮기기(config) · compose 다름(빌드·배포) · EOL(서버)
  expect(screen.getByText('shop web · prod')).toBeInTheDocument()
  expect(screen.getAllByText('shop/web').length).toBeGreaterThan(0)
  expect(screen.queryByText('old/was')).toBeNull()
  expect(await screen.findByText('node 10.24.0')).toBeInTheDocument()
  expect(screen.getByText('python 3.6.8')).toBeInTheDocument()
  expect(screen.queryByText('new-01')).not.toBeInTheDocument() // node 20 은 경고 아님
  // 수집 현황: 탭마다 한 줄
  expect(screen.getByText('CI 배포 방식').closest('tr')).toHaveTextContent('파일 복사 2compose 다름 1executor 추정 1')
  expect(screen.getByText('이미지 · 처음 실행할 명령').closest('tr')).toHaveTextContent('못 읽음 1')
  expect(screen.getByText(/데이터 기준 2026-09-1[45]/)).toBeInTheDocument()
})

test('API 실패 시 안내', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
  render(<Dashboard />)
  expect(await screen.findByText(/API 연결 실패/)).toBeInTheDocument()
})
