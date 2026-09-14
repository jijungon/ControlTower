import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Conf from './Conf'

test('conf 드리프트/동기화 배지 렌더', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(
        JSON.stringify([
          { server_id: 1, hostname: 'web-01', path: '/etc/nginx/nginx.conf', status: 'synced' },
          { server_id: 2, hostname: 'web-02', path: '/etc/nginx/nginx.conf', status: 'drift', detail: 'gzip 누락' },
        ]),
        { status: 200 },
      ),
    ),
  )
  render(<Conf />)
  expect(await screen.findByText('동기화됨')).toBeInTheDocument()
  expect(screen.getByText('드리프트')).toBeInTheDocument()
  expect(screen.getByText('gzip 누락')).toBeInTheDocument()
})
