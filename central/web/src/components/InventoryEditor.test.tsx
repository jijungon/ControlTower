import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import Servers from '../pages/Servers'

// 서버 탭 '목록 고치기' — 운영자 · 스위치 켜짐(can_edit)일 때만, 바뀐 것 확인 뒤 저장, 실패 · 모름은 그대로

const ACCESS = {
  state: 'ok',
  can_edit: true,
  viewer: { email: 'ops@example.com', role: '운영자' },
  people: [
    { email: 'server-admin 그룹 전원', role: 'admin', gw_account: 'ubuntu', server_account: 'ubuntu', where: [{ env: 'dev', service: 'shop' }] },
  ],
  envs: [
    { env: 'dev', audience: '개발자 · 운영자', services: [
      { name: 'shop', gw: { host: '198.51.100.20', port: 22 }, servers: [{ name: 'api', addr: '192.0.2.10' }, { name: 'worker', addr: '192.0.2.11' }], developers: [] }] },
  ],
}

const ENTRY = {
  env: 'dev', service: 'shop', version: 3, updated_at: '2026-10-28T00:02:00Z',
  last_edit: { here: false, by: null, at: null },
  gw: { host: '198.51.100.20', port: 22 }, servers: { api: '192.0.2.10', worker: '192.0.2.11' }, users_count: 1,
}

type Route = (init?: RequestInit) => Response | Promise<Response>
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

function mockFetch(routes: Record<string, Route>, access: unknown = ACCESS) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    if (routes[key]) return routes[key](init)
    if (String(url).includes('/api/access')) return json(access)
    return json([])
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const sent = (m: ReturnType<typeof mockFetch>, key: string) =>
  m.mock.calls.filter(([u, i]) => `${i?.method ?? 'GET'} ${u}` === key).map(([, i]) => JSON.parse(String(i?.body)))

async function openEditor() {
  fireEvent.click(await screen.findByRole('button', { name: '목록 고치기' }))
  fireEvent.click(screen.getByRole('button', { name: 'shop 고치기' }))
  return screen.findByRole('group', { name: 'dev/shop 고치기' })
}

afterEach(() => vi.unstubAllGlobals())

test('스위치가 꺼졌거나 운영자가 아니면(can_edit 없음) 고치기 버튼이 없다', async () => {
  mockFetch({}, { ...ACCESS, can_edit: false })
  const { unmount } = render(<Servers />)
  await screen.findByRole('complementary', { name: '사람' })
  expect(screen.queryByRole('button', { name: '목록 고치기' })).toBeNull()
  unmount()
  const { can_edit: _, ...old } = ACCESS // 옛 API(칸 없음)도 못 고침으로
  mockFetch({}, old)
  render(<Servers />)
  await screen.findByRole('complementary', { name: '사람' })
  expect(screen.queryByRole('button', { name: '목록 고치기' })).toBeNull()
})

test('고치기 → 금고에서 새로 읽고(판 · 누가) · 사람은 못 고친다고 · 바뀐 것 확인 → 저장 → 새 판', async () => {
  const m = mockFetch({
    'GET /api/inventory/dev/shop': () => json(ENTRY),
    'POST /api/inventory/dev/shop/preview': () => json({ version: 3, changes: [
      { kind: 'server_remove', name: 'worker', from: '192.0.2.11' },
      { kind: 'server_add', name: 'api-2', to: '192.0.2.12' },
      { kind: 'server_addr', name: 'api', from: '192.0.2.10', to: '192.0.2.99' },
    ] }),
    'PUT /api/inventory/dev/shop': () => json({ saved: true, version: 4, updated_at: '2026-10-28T00:03:00Z', changes: [] }),
  })
  render(<Servers />)
  const ed = await openEditor()
  expect(screen.getByText(/사람\(누가\)은 못 고쳐요/)).toBeInTheDocument()
  expect(await within(ed).findByText('금고 v3')).toBeInTheDocument()
  expect(ed).toHaveTextContent('ControlTower 밖(gw 의 idp-login 등)')
  expect(ed).toHaveTextContent('사람 1명은 여기서 못 고쳐요')
  expect(within(ed).queryByText('dev1@example.com')).toBeNull()

  fireEvent.change(within(ed).getByLabelText('서버 주소 1'), { target: { value: ' 192.0.2.99 ' } })
  fireEvent.click(within(ed).getAllByRole('button', { name: '빼기' })[1]) // worker
  fireEvent.click(within(ed).getByRole('button', { name: '서버 더하기' }))
  fireEvent.change(within(ed).getByLabelText('서버 이름 2'), { target: { value: 'api-2' } })
  fireEvent.change(within(ed).getByLabelText('서버 주소 2'), { target: { value: '192.0.2.12' } })
  fireEvent.click(within(ed).getByRole('button', { name: '바뀐 것 보기' }))

  const list = await within(ed).findByRole('list', { name: '바뀌는 것' })
  expect(list).toHaveTextContent('서버 뺌 worker (192.0.2.11)')
  expect(list).toHaveTextContent('서버 추가 api-2 (192.0.2.12)')
  expect(list).toHaveTextContent('서버 주소 바뀜 api: 192.0.2.10 → 192.0.2.99')
  const body = { version: 3, gw: { host: '198.51.100.20', port: 22 }, servers: { api: '192.0.2.99', 'api-2': '192.0.2.12' } }
  expect(sent(m, 'POST /api/inventory/dev/shop/preview')).toEqual([body])
  expect(sent(m, 'PUT /api/inventory/dev/shop')).toEqual([]) // 확인만으로는 안 씀

  const accessCalls = () => m.mock.calls.filter(([u]) => String(u) === '/api/access').length
  const before = accessCalls()
  fireEvent.click(within(ed).getByRole('button', { name: '저장' }))
  expect(await within(ed).findByRole('status')).toHaveTextContent('저장했어요 — 금고 v4')
  expect(sent(m, 'PUT /api/inventory/dev/shop')).toEqual([body])
  await waitFor(() => expect(accessCalls()).toBeGreaterThan(before)) // 왼쪽 · 오른쪽 목록도 다시
})

test('그 사이 idp-login 이 먼저 고쳤으면(409) 저장했다고 하지 않고 "다시 불러온 뒤 고쳐 주세요" + 다시 불러오기', async () => {
  let version = 3
  mockFetch({
    'GET /api/inventory/dev/shop': () => json({ ...ENTRY, version }),
    'POST /api/inventory/dev/shop/preview': () => json({ version: 3, changes: [{ kind: 'server_remove', name: 'worker', from: '192.0.2.11' }] }),
    'PUT /api/inventory/dev/shop': () => json({ detail: '다른 곳(idp-login 등)에서 먼저 고쳤어요 — 다시 불러온 뒤 고쳐 주세요 (v3 뒤에 바뀜)' }, 409),
  })
  render(<Servers />)
  const ed = await openEditor()
  await within(ed).findByText('금고 v3')
  fireEvent.click(within(ed).getAllByRole('button', { name: '빼기' })[1])
  fireEvent.click(within(ed).getByRole('button', { name: '바뀐 것 보기' }))
  fireEvent.click(await within(ed).findByRole('button', { name: '저장' }))
  const alert = await within(ed).findByRole('alert')
  expect(alert).toHaveTextContent('다시 불러온 뒤 고쳐 주세요')
  expect(ed).not.toHaveTextContent('저장했어요')
  version = 4
  fireEvent.click(within(alert).getByRole('button', { name: '다시 불러오기' }))
  expect(await within(ed).findByText('금고 v4')).toBeInTheDocument()
  expect(within(ed).getByRole('status')).toHaveTextContent('금고에서 다시 불러왔어요')
})

test.each([
  ['금고가 답을 못 줌(502)', () => json({ detail: '저장됐는지 모름 — 다시 불러와 확인해 주세요: HTTP 504' }, 502), '저장됐는지 모름 — 다시 불러와 확인해 주세요'],
  ['네트워크가 끊김', () => Promise.reject(new TypeError('Failed to fetch')), '저장됐는지 모름 — 답을 못 받았어요'],
  ['금고가 거절(정책 없음)', () => json({ detail: '금고가 저장을 거절했어요(아무것도 안 바뀜): HTTP 403 — permission denied' }, 502), '저장 못 했어요 — 금고가 저장을 거절했어요(아무것도 안 바뀜)'],
])('저장이 %s → 됐다고 보이지 않는다', async (_, put, text) => {
  mockFetch({
    'GET /api/inventory/dev/shop': () => json(ENTRY),
    'POST /api/inventory/dev/shop/preview': () => json({ version: 3, changes: [{ kind: 'gw_port', from: 22, to: 2222 }] }),
    'PUT /api/inventory/dev/shop': put,
  })
  render(<Servers />)
  const ed = await openEditor()
  await within(ed).findByText('금고 v3')
  fireEvent.change(within(ed).getByLabelText('gw 포트'), { target: { value: '2222' } })
  fireEvent.click(within(ed).getByRole('button', { name: '바뀐 것 보기' }))
  fireEvent.click(await within(ed).findByRole('button', { name: '저장' }))
  expect(await within(ed).findByRole('alert')).toHaveTextContent(text)
  expect(ed).not.toHaveTextContent('저장했어요')
})

test('금고를 못 읽으면 "목록 모름" — 예전 값으로 고칠 칸을 보여 주지 않는다', async () => {
  mockFetch({ 'GET /api/inventory/dev/shop': () => json({ detail: '목록 모름 — 금고를 못 읽었어요: HTTP 503' }, 502) })
  render(<Servers />)
  const ed = await openEditor()
  expect(await within(ed).findByText(/목록 모름 — 목록 모름 — 금고를 못 읽었어요: HTTP 503/)).toBeInTheDocument()
  expect(within(ed).queryByLabelText('gw 주소')).toBeNull()
  expect(within(ed).queryByRole('button', { name: '바뀐 것 보기' })).toBeNull()
})

test('이름이 겹치거나 반만 적으면 보내지 않고 화면에서 막는다', async () => {
  const m = mockFetch({ 'GET /api/inventory/dev/shop': () => json(ENTRY) })
  render(<Servers />)
  const ed = await openEditor()
  await within(ed).findByText('금고 v3')
  fireEvent.change(within(ed).getByLabelText('서버 이름 2'), { target: { value: 'api' } })
  fireEvent.click(within(ed).getByRole('button', { name: '바뀐 것 보기' }))
  expect(await within(ed).findByRole('alert')).toHaveTextContent('서버 이름이 겹쳐요: api')
  fireEvent.change(within(ed).getByLabelText('서버 이름 2'), { target: { value: 'worker' } })
  fireEvent.change(within(ed).getByLabelText('서버 주소 2'), { target: { value: '' } })
  fireEvent.click(within(ed).getByRole('button', { name: '바뀐 것 보기' }))
  expect(await within(ed).findByRole('alert')).toHaveTextContent('서버 이름과 주소를 둘 다 적어 주세요 (worker)')
  expect(m.mock.calls.some(([, i]) => i?.method === 'POST' || i?.method === 'PUT')).toBe(false)
})
