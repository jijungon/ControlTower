import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Servers from './Servers'

const ACCESS = {
  state: 'ok',
  viewer: { email: 'joji@example.com', role: '운영자' },
  people: [
    { email: 'server-admin 그룹 전원', role: 'admin', gw_account: 'ubuntu', server_account: 'ubuntu',
      note: 'appuser 는 sudo -iu appuser',
      where: [{ env: 'dev', service: 'oci-idp' }, { env: 'prod', service: 'shop' }] },
    { email: 'devtest@example.local', role: 'developer', gw_account: 'devtest', server_account: 'appuser',
      where: [{ env: 'dev', service: 'oci-idp' }] },
  ],
  envs: [
    { env: 'dev', audience: '개발자 · 운영자', services: [
      { name: 'oci-idp', gw: { host: '198.51.100.7', port: 22 }, servers: [{ name: 'idp-test', addr: '192.0.2.16' }], developers: ['devtest@example.local'] }] },
    { env: 'prod', audience: '운영자만', services: [
      { name: 'shop', gw: { host: '198.51.100.9', port: 22 }, servers: [], developers: [] }] },
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

test('서버 탭 = 왼쪽 사람(운영자·개발자 · 계정) / 가운데 선 / 오른쪽 환경 → gw → 서버, 예전 서버 목록 API 는 안 부름', async () => {
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
  expect(screen.queryByText(/운영자 — 주황 · 굵고 긴 점선/)).toBeNull() // 선 색 범례는 뺌(배지 · 테두리 색으로 충분)
  expect(screen.getByText(/gw · 서버 줄을 누르면 칠 명령/)).toBeInTheDocument()

  const places = screen.getByRole('region', { name: '환경 · gw · 서버' })
  expect(places).toHaveTextContent('oci-idp · gw')
  expect(places).toHaveTextContent('idp-test')
  expect(places).not.toHaveTextContent('idp-login ssh') // 명령은 처음부터 늘어놓지 않음

  expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/api/servers'))).toBe(false)
  expect(await screen.findByRole('heading', { name: '서버 설정 파일 (/etc)' })).toBeInTheDocument()
})

test('선은 사람이 실제로 갈 수 있는 환경까지만 — 운영자는 보이는 모든 환경, 개발자는 그 사람의 where', async () => {
  mockFetch(ACCESS)
  render(<Servers />)
  await screen.findByRole('complementary', { name: '사람' })
  expect(screen.getByTestId('link-server-admin 그룹 전원-dev')).toHaveClass('access-link--admin')
  expect(screen.getByTestId('link-server-admin 그룹 전원-prod')).toHaveClass('access-link--admin')
  expect(screen.getByTestId('link-devtest@example.local-dev')).toHaveClass('access-link--developer')
  expect(screen.queryByTestId('link-devtest@example.local-prod')).toBeNull()
  // 환경 오른쪽 위 점: dev 는 주황 · 청록, prod 는 주황 하나
  expect(within(screen.getByTestId('env-dev')).getByTitle('운영자가 갈 수 있음')).toBeInTheDocument()
  expect(within(screen.getByTestId('env-dev')).getByTitle('개발자가 갈 수 있음')).toBeInTheDocument()
  expect(within(screen.getByTestId('env-prod')).getByTitle('운영자가 갈 수 있음')).toBeInTheDocument()
  expect(within(screen.getByTestId('env-prod')).queryByTitle('개발자가 갈 수 있음')).toBeNull()
})

test('사람에 마우스를 올리면 그 사람 선 · 갈 수 있는 환경만 남고, 떼면 원래대로', async () => {
  mockFetch(ACCESS)
  render(<Servers />)
  const dev = await screen.findByRole('button', { name: /devtest@example.local/ })
  fireEvent.mouseEnter(dev)
  expect(screen.getByTestId('link-server-admin 그룹 전원-dev')).toHaveClass('access-link--dim')
  expect(screen.getByTestId('link-devtest@example.local-dev')).not.toHaveClass('access-link--dim')
  expect(screen.getByTestId('env-prod')).toHaveClass('access-env--dim')
  expect(screen.getByTestId('env-dev')).not.toHaveClass('access-env--dim')
  fireEvent.mouseLeave(dev)
  expect(screen.getByTestId('link-server-admin 그룹 전원-dev')).not.toHaveClass('access-link--dim')
  expect(screen.getByTestId('env-prod')).not.toHaveClass('access-env--dim')
})

test('아무도 안 골랐으면 gw · 서버 줄을 누를 때 보는 사람 자신(운영자 = ubuntu) 명령, 다시 누르면 닫힘', async () => {
  mockFetch(ACCESS)
  render(<Servers />)
  const gw = within(await screen.findByTestId('gw-dev-oci-idp')).getByRole('button', { name: /oci-idp · gw/ })
  fireEvent.click(gw)
  expect(gw).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByTestId('gw-dev-oci-idp')).toHaveTextContent('나 (운영자) 기준idp-login ssh ubuntu dev oci-idp')
  fireEvent.click(within(screen.getByTestId('gw-dev-oci-idp')).getByRole('button', { name: /idp-test/ }))
  expect(screen.getByTestId('gw-dev-oci-idp')).toHaveTextContent('gw 안에서: idp-login ssh ubuntu dev idp-test')
  expect(screen.getByTestId('gw-dev-oci-idp')).not.toHaveTextContent('idp-login ssh ubuntu dev oci-idp') // 한 번에 하나만
  fireEvent.click(within(screen.getByTestId('gw-dev-oci-idp')).getByRole('button', { name: /idp-test/ }))
  expect(screen.getByRole('region', { name: '환경 · gw · 서버' })).not.toHaveTextContent('idp-login ssh')
})

test('개발자를 고르면 그 사람 계정으로(gw 개인 · 서버 appuser), 못 가는 곳은 명령 대신 "못 들어가요"', async () => {
  mockFetch(ACCESS)
  render(<Servers />)
  const dev = await screen.findByRole('button', { name: /devtest@example.local/ })
  fireEvent.click(dev)
  expect(dev).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByTestId('gw-prod-shop')).toHaveClass('access-gw--dim')
  expect(screen.getByTestId('gw-dev-oci-idp')).not.toHaveClass('access-gw--dim')
  const devGw = screen.getByTestId('gw-dev-oci-idp')
  fireEvent.click(within(devGw).getByRole('button', { name: /oci-idp · gw/ }))
  expect(devGw).toHaveTextContent('devtest@example.local 기준idp-login ssh devtest dev oci-idp')
  fireEvent.click(within(devGw).getByRole('button', { name: /idp-test/ }))
  expect(devGw).toHaveTextContent('gw 안에서: idp-login ssh appuser dev idp-test')
  // 못 가는 곳에 그 사람 명령을 보여 주지 않는다
  fireEvent.click(within(screen.getByTestId('gw-prod-shop')).getByRole('button', { name: /shop · gw/ }))
  expect(screen.getByTestId('gw-prod-shop')).toHaveTextContent('이 사람은 못 들어가요')
  expect(screen.getByRole('region', { name: '환경 · gw · 서버' })).not.toHaveTextContent('idp-login ssh devtest prod')
})

test('보는 사람이 개발자면 자기 계정으로, 금고 목록에 없으면 명령 대신 "내 계정이 목록에 없어요"', async () => {
  const asDev = { ...ACCESS, viewer: { email: 'DevTest@example.local', role: '개발자' }, envs: [ACCESS.envs[0]] }
  mockFetch(asDev)
  const { unmount } = render(<Servers />)
  const gw = await screen.findByTestId('gw-dev-oci-idp')
  fireEvent.click(within(gw).getByRole('button', { name: /oci-idp · gw/ }))
  expect(gw).toHaveTextContent('나 (devtest@example.local) 기준idp-login ssh devtest dev oci-idp')
  unmount()
  mockFetch({ ...asDev, viewer: { email: 'new@example.local', role: '개발자' } })
  render(<Servers />)
  const gw2 = await screen.findByTestId('gw-dev-oci-idp')
  fireEvent.click(within(gw2).getByRole('button', { name: /oci-idp · gw/ }))
  expect(gw2).toHaveTextContent('내 계정이 금고 목록에 없어요')
  expect(gw2).not.toHaveTextContent('idp-login ssh')
})

test('[복사] 는 명령만 복사한다("gw 안에서:" 는 빼고)', async () => {
  const writeText = vi.fn(async () => {})
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  mockFetch(ACCESS)
  render(<Servers />)
  const gw = await screen.findByTestId('gw-dev-oci-idp')
  fireEvent.click(within(gw).getByRole('button', { name: /idp-test/ }))
  fireEvent.click(within(gw).getByRole('button', { name: '복사' }))
  expect(writeText).toHaveBeenCalledWith('idp-login ssh ubuntu dev idp-test')
  expect(await within(gw).findByRole('button', { name: '복사됨' })).toBeInTheDocument()
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

test('로그인 정보(그룹)를 모르면 빈 목록 · "권한 없음" 이 아니라 "몰라서 막아 두었어요" 를 보여 준다', async () => {
  mockFetch({ state: 'no_identity', viewer: { email: null, role: '모름' }, envs: [], people: [] })
  render(<Servers />)
  expect(await screen.findByText(/로그인 정보\(그룹\)를 몰라 목록을 보여 줄 수 없어요/)).toBeInTheDocument()
  expect(screen.queryByText(/볼 수 있는 목록이 없어요/)).toBeNull()
})
