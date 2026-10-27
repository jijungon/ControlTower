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

test('제품 버전도 넣었으면 같이', async () => {
  serve({ version: 'v1.2.0', build: 'b02dc5d', started_at: null })
  render(<VersionTag />)
  expect((await screen.findByRole('link')).textContent).toBe('v1.2.0 · b02dc5d')
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
