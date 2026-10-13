import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import ConfigRepo from './ConfigRepo'
import type { ConfigRow } from '../api'

const ROWS: ConfigRow[] = [
  { path: 'shop/web', runtime: 'node', runtime_version: '18', base_image: 'infra/nodejs', base_tag: 'v18', start: 'start.sh', start_files: ['node-startup.sh'], state: 'legacy', compose: { prod: 'mount', dev: 'command' }, collected_at: '2026-10-13T03:00:00+00:00',
    code: { node: '22', node_from: '.nvmrc', node_rule: 'exact', nest: '11.0.1' } }, // 코드 22 ≠ 이미지 18 → ⚠
  { path: 'shop/admin', runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: ['node-startup.sh'], state: 'leftover',
    code: { node: '20', node_from: 'package.json', node_rule: 'min' } }, // ≥20 이고 이미지 22 → 괜찮음
  { path: 'shop/api', runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: [], state: 'done' },
  { path: 'shop/was', runtime: 'java', runtime_version: '17', base_image: 'infra/springboot', base_tag: '0.1.3-java17', start: 'base', start_files: [], state: 'base' },
  { path: 'shop/empty', state: 'none' },
]

test('폴더별 실행 명령 위치·상태·start.sh 형태 + 오래된 버전 빨간 칸', async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(ROWS), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  render(<ConfigRepo />)
  const table = within(await screen.findByRole('table'))
  expect(table.getByText('⚠ node 18')).toHaveClass('ver--old') // 최신 22
  expect(table.getAllByText('node 22')[0]).not.toHaveClass('ver--old')
  expect(table.getByText('구형')).toHaveAttribute('title', 'start.sh 로 실행 — Dockerfile CMD 로 바꿀 대상')
  expect(table.getByText('start.sh 잔재')).toBeInTheDocument()
  expect(table.getByText('완료')).toBeInTheDocument()
  expect(table.getByText('해당 없음')).toBeInTheDocument()
  expect(table.getByText('Dockerfile 없음')).toBeInTheDocument()
  expect(table.getAllByText('Dockerfile (CMD)').length).toBe(2)
  // start.sh 형태: 환경 순서(dev → prod)대로, shell(마운트) / compose(command:)
  const badges = table.getAllByText(/^(dev|stg|prod) (shell|compose|Dockerfile)$/).map((b) => b.textContent)
  expect(badges).toEqual(['dev compose', 'prod shell'])
  expect(table.getByText('prod shell')).toHaveClass('badge--warn')
  expect(table.getByText('dev compose')).toHaveClass('badge--ok')
  expect(screen.getByText(/start\.sh 구형 1 · 잔재 1 · 완료 1 · 코드↔이미지 다름 1 · 오래된 버전 1칸 · 최신: node 22 · java 17/)).toBeInTheDocument()
  // 코드에 적힌 버전: 이미지와 다르면 ⚠, '≥' 는 최소 버전이라 이미지가 더 높으면 괜찮음
  const diff = table.getByText('⚠ 이미지와 다름')
  expect(diff).toHaveAttribute('title', '코드는 node 22(.nvmrc), 이미지는 node 18')
  expect(diff.parentElement).toHaveTextContent(/^node 22⚠ 이미지와 다름nest 11\.0\.1$/)
  expect(table.getByText('node ≥20')).toBeInTheDocument()
  expect(table.getAllByText('⚠ 이미지와 다름').length).toBe(1)
  expect(table.getByText('nest 11.0.1')).toBeInTheDocument()
  expect(screen.getByText(/출처: center config repo/)).toBeInTheDocument()
  // 서비스별로 묶음: shop 의 5개 폴더가 한 칸
  expect(table.getByText('shop').closest('td')).toHaveAttribute('rowspan', '5')
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
