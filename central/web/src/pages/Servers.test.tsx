import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Servers from './Servers'

function routed(servers: unknown, groups: unknown = [], serversOk = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/api/groups')) return new Response(JSON.stringify(groups), { status: 200 })
      if (url.includes('/api/conf')) return new Response('[]', { status: 200 }) // 같은 탭의 /etc 설정 파일 섹션
      if (url.includes('/api/versions'))
        return new Response(
          JSON.stringify([
            { kind: 'server', name: 'web-01', tools: { node: '18.19.0', docker: '24.0.7' } },
            { kind: 'server', name: 'db-01', tools: { node: '20.11.1' } },
            { kind: 'repo', name: 'shop', tools: { node: '22' } }, // repo 줄은 서버 탭에서 안 씀
          ]),
          { status: 200 },
        )
      return new Response(JSON.stringify(servers), { status: serversOk ? 200 : 500 })
    }),
  )
}

test('서버 목록에 그룹·태그·인증(2FA)을 렌더', async () => {
  routed(
    [
      { id: 1, hostname: 'web-01', ip: '10.0.0.1', ssh_user: 'deploy', status: 'online', needs_2fa: false, group: 'prod', tags: ['edge', 'nginx'] },
      { id: 2, hostname: 'db-01', ip: '10.0.0.2', ssh_user: 'root', status: 'offline', needs_2fa: true, tags: [] },
    ],
    [{ id: 1, name: 'prod', count: 1 }],
  )
  render(<Servers />)
  expect(await screen.findByText('web-01')).toBeInTheDocument()
  expect(screen.getByText('prod')).toBeInTheDocument()
  expect(screen.getByText('edge')).toBeInTheDocument()
  expect(screen.getByText('2FA')).toBeInTheDocument() // db-01: 추가 인증 필요
  expect(screen.getByText('키만')).toBeInTheDocument() // web-01: 키 단독
})

test('빈 상태 안내', async () => {
  routed([], [])
  render(<Servers />)
  expect(await screen.findByText(/임포트된 서버가 없습니다/)).toBeInTheDocument()
})

test('API 에러 상태 안내', async () => {
  routed({}, [], false)
  render(<Servers />)
  expect(await screen.findByText(/API에 연결하지 못했습니다/)).toBeInTheDocument()
})

test('서버 탭 안에 서버 설정 파일(/etc) 섹션과 새로고침', async () => {
  routed([{ id: 1, hostname: 'web-01', ssh_user: 'deploy', status: 'online', last_checked_at: '2026-10-13T03:00:00+00:00', tags: [] }])
  render(<Servers />)
  expect(await screen.findByText('web-01')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '서버 설정 파일 (/etc)' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '서버 목록 새로고침' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '서버 설정 파일 (/etc) 새로고침' })).toBeInTheDocument()
  expect(screen.getAllByText(/데이터 기준 2026-10-13/).length).toBeGreaterThanOrEqual(1)
})

test('서버마다 깔린 도구 버전 — 같은 도구 중 최신이 아니면 빨간 칸', async () => {
  routed([
    { id: 1, hostname: 'web-01', ssh_user: 'deploy', status: 'online', tags: [] },
    { id: 2, hostname: 'db-01', ssh_user: 'root', status: 'online', tags: [] },
  ])
  render(<Servers />)
  expect(await screen.findByText('⚠ node 18.19.0')).toHaveClass('ver--old') // db-01 의 node 20 보다 낮음
  expect(screen.getByText('node 20.11.1')).not.toHaveClass('ver--old')
  expect(screen.getByText('docker 24.0.7')).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: '깔린 도구' })).toBeInTheDocument()
  expect(screen.getByText(/출처: 내 PC 의 ~\/\.ssh\/config/)).toBeInTheDocument()
})
