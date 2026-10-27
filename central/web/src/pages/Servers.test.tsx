import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Servers from './Servers'

const ACCESS = {
  state: 'ok',
  viewer: { email: 'joji@example.com', role: '운영자' },
  people: [
    { email: 'server-admin 그룹 전원', role: 'admin', gw_account: 'ubuntu', server_account: 'ubuntu',
      note: 'appuser 는 sudo -iu appuser',
      where: [{ env: 'dev', service: 'oci-idp' }, { env: 'prod', service: 'supercycl' }] },
    { email: 'devtest@example.local', role: 'developer', gw_account: 'devtest', server_account: 'appuser',
      where: [{ env: 'dev', service: 'oci-idp' }] },
  ],
  envs: [
    { env: 'dev', audience: '개발자 · 운영자', services: [
      { name: 'oci-idp', gw: { host: '198.51.100.7', port: 22 }, servers: [{ name: 'idp-test', addr: '192.0.2.16' }], developers: ['devtest@example.local'] }] },
    { env: 'prod', audience: '운영자만', services: [
      { name: 'supercycl', gw: { host: '198.51.100.9', port: 22 }, servers: [], developers: [] }] },
  ],
}

function mockFetch(access: unknown) {
  const fetchMock = vi.fn(async (url: string) =>
    String(url).includes('/api/access')
      ? new Response(JSON.stringify(access), { status: 200 })
      : new Response('[]', { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

test('서버 탭 = 왼쪽 사람(운영자·개발자 · 계정) / 오른쪽 환경 → gw → 서버, 예전 서버 목록 API 는 안 부름', async () => {
  const fetchMock = mockFetch(ACCESS)
  render(<Servers />)
  expect(screen.getByRole('heading', { name: '서버' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '누가 · 어디로' })).toBeInTheDocument()

  const people = await screen.findByRole('complementary', { name: '사람' })
  const admin = within(people).getByRole('button', { name: /server-admin 그룹 전원/ })
  expect(admin).toHaveTextContent('운영자')
  expect(admin).toHaveTextContent('gw ubuntu · 서버 ubuntu')
  const dev = within(people).getByRole('button', { name: /devtest@example.local/ })
  expect(dev).toHaveTextContent('개발자')
  expect(dev).toHaveTextContent('gw devtest (개인) · 서버 appuser')

  const places = screen.getByRole('region', { name: '환경 · gw · 서버' })
  expect(places).toHaveTextContent('oci-idp · gw')
  expect(places).toHaveTextContent('idp-test')
  expect(places).toHaveTextContent('idp-login ssh ubuntu dev oci-idp')

  expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/api/servers'))).toBe(false)
  expect(await screen.findByRole('heading', { name: '서버 설정 파일 (/etc)' })).toBeInTheDocument()
})

test('개발자를 누르면 그 사람이 갈 곳만 또렷하고, 명령도 그 사람 계정으로 바뀐다', async () => {
  mockFetch(ACCESS)
  render(<Servers />)
  const dev = await screen.findByRole('button', { name: /devtest@example.local/ })
  fireEvent.click(dev)
  expect(dev).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByTestId('gw-prod-supercycl')).toHaveClass('access-gw--dim')
  expect(screen.getByTestId('gw-dev-oci-idp')).not.toHaveClass('access-gw--dim')
  const places = screen.getByRole('region', { name: '환경 · gw · 서버' })
  expect(places).toHaveTextContent('idp-login ssh devtest dev oci-idp')
  expect(places).toHaveTextContent('idp-login ssh appuser dev idp-test')
  // 못 가는 곳에 그 사람 명령을 보여 주지 않는다
  expect(screen.getByTestId('gw-prod-supercycl')).toHaveTextContent('devtest@example.local 은 못 들어감')
  expect(places).not.toHaveTextContent('idp-login ssh devtest prod')
})

test('금고에 연결 전이면 빈 목록이 아니라 "연결하지 않았어요" 를, 못 읽으면 "목록 모름" 을 보여 준다', async () => {
  mockFetch({ state: 'off', viewer: { email: null, role: '' }, envs: [], people: [] })
  const { unmount } = render(<Servers />)
  expect(await screen.findByText(/금고 목록에 아직 연결하지 않았어요/)).toBeInTheDocument()
  unmount()
  mockFetch({ state: 'error', error: 'AppRole 로그인 실패', viewer: { email: null, role: '' }, envs: [], people: [] })
  render(<Servers />)
  expect(await screen.findByText(/목록 모름 — 금고를 못 읽었어요: AppRole 로그인 실패/)).toBeInTheDocument()
})
