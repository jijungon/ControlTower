import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })))
})

test('기본 탭은 대시보드, 탭 클릭 시 전환', async () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: '대시보드' })).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: '서버' }))
  expect(screen.getByRole('heading', { name: /서버 · 접속키/ })).toBeInTheDocument()
})
