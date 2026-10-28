import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import VersionTag from './VersionTag'

function serve(reply: object | 'fail' | number) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      if (reply === 'fail') throw new TypeError('Failed to fetch')
      if (typeof reply === 'number') return new Response('x', { status: reply })
      return new Response(JSON.stringify(reply), { status: 200 })
    }),
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('반영할 때 커밋을 넣었으면 — 커밋(GitHub 링크) · 반영 시각', async () => {
  serve({ version: 'dev', build: 'b02dc5d', started_at: '2026-10-27T05:05:00+00:00' })
  render(<VersionTag />)
  const link = await screen.findByRole('link', { name: 'b02dc5d' })
  expect(link).toHaveAttribute('href', 'https://github.com/jijungon/ControlTower/commit/b02dc5d')
  expect(link.parentElement).toHaveTextContent(/^b02dc5d · \d\d\/\d\d \d\d:\d\d 반영$/)
})

test('버전 태그 v0.0.{PR} — 버전은 PR 로, 커밋은 커밋으로 이어짐', async () => {
  serve({ version: 'v0.0.69', build: 'b02dc5d', started_at: '2026-10-28T01:15:00+00:00' })
  render(<VersionTag />)
  const ver = await screen.findByRole('link', { name: 'v0.0.69' })
  expect(ver).toHaveAttribute('href', 'https://github.com/jijungon/ControlTower/pull/69')
  expect(screen.getByRole('link', { name: 'b02dc5d' })).toHaveAttribute('href', 'https://github.com/jijungon/ControlTower/commit/b02dc5d')
  expect(ver.parentElement).toHaveTextContent(/^v0\.0\.69 · b02dc5d · \d\d\/\d\d \d\d:\d\d 반영$/) // 이슈가 없으면 이슈 칸만 빠짐
})

test('이슈가 있으면 v0.0.{PR} · 이슈 #N(여럿이면 · 로) — 이슈로 이어짐', async () => {
  serve({ version: 'v0.0.69+59.60', build: 'b02dc5d', started_at: null })
  render(<VersionTag />)
  const ver = await screen.findByRole('link', { name: 'v0.0.69' })
  expect(ver.parentElement).toHaveTextContent(/^v0\.0\.69 · 이슈 #59 · #60 · b02dc5d$/)
  expect(screen.getByRole('link', { name: '#59' })).toHaveAttribute('href', 'https://github.com/jijungon/ControlTower/issues/59')
  expect(screen.getByRole('link', { name: '#60' })).toHaveAttribute('href', 'https://github.com/jijungon/ControlTower/issues/60')
})

test('다른 모양의 버전(예: v1.2.0)은 글자 그대로 — PR 번호를 지어내지 않음', async () => {
  serve({ version: 'v1.2.0', build: 'b02dc5d', started_at: null })
  render(<VersionTag />)
  const commit = await screen.findByRole('link', { name: 'b02dc5d' })
  expect(commit.parentElement).toHaveTextContent(/^v1\.2\.0 · b02dc5d$/)
  expect(screen.getAllByRole('link')).toHaveLength(1)
})

test('반영할 때 안 넣었으면(dev) — "버전 모름", 지어내지 않음', async () => {
  serve({ version: 'dev', build: 'dev', started_at: '2026-10-27T05:05:00+00:00' })
  render(<VersionTag />)
  expect(await screen.findByText(/^버전 모름\(dev\) · \d\d\/\d\d \d\d:\d\d 시작$/)).toBeInTheDocument()
  expect(screen.queryByRole('link')).toBeNull()
})

test.each([['fail' as const], [502]])('못 불러오면(%s) — "버전 모름"', async (reply) => {
  serve(reply)
  render(<VersionTag />)
  expect(await screen.findByText('버전 모름')).toBeInTheDocument()
})
