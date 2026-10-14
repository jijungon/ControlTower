import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Ops from './Ops'

test('OS 패치(왼쪽)와 작업이력(오른쪽)을 한 페이지에', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/api/audit'))
        return new Response(JSON.stringify([{ id: 1, actor: 'runner', action: 'cicd.config', target_type: 'cicd', detail: '15개', created_at: '2026-10-13T03:00:00+00:00' }]), { status: 200 })
      return new Response(JSON.stringify([{ server_id: 1, hostname: 'web-01', pending: 1, security: 1, packages: [], collected_at: '2026-10-12T03:00:00+00:00' }]), { status: 200 })
    }),
  )
  const { container } = render(<Ops />)
  expect(await screen.findByText('config 수집')).toBeInTheDocument() // 새 작업 라벨
  expect(await screen.findByText('web-01')).toBeInTheDocument()
  const split = container.querySelector('.split')!
  expect(split.children.length).toBe(2)
  expect(split.children[0].textContent).toContain('OS 패치')
  expect(split.children[1].textContent).toContain('작업이력 (전체)')
})
