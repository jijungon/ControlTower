import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import AccessLog from './AccessLog'

// 나노초까지 오는 금고 시각(수집기가 마이크로초로 자른 모양 · 자르기 전 모양 둘 다 읽혀야 함)
const iso = (minutesAgo: number, frac = '.322348939') => new Date(Date.now() - minutesAgo * 60_000).toISOString().replace(/\.\d{3}Z$/, `${frac}Z`)
const JWT = 'jwt-' + 'a1'.repeat(32) // 이메일을 적기 전 사람 로그인 — 금고엔 이 이름만 남음

const EVENTS = [
  { at: iso(5), kind: 'person', who: 'dev@example.com', env: 'prod', account: 'ubuntu', role: 'prod-ubuntu', serial: '11d1bda82b498807', result: 'denied',
    reason: '1 error occurred:\n\t* permission denied\n\n' },
  { at: iso(20, '.5'), kind: 'person', who: 'dev@example.com', env: 'dev', account: null, role: 'dev-gw', serial: null, result: 'issued', reason: null },
  { at: iso(30, '.000001'), kind: 'machine', who: 'runner', env: 'dev', account: 'appuser', role: 'dev-runner', serial: null, result: 'issued', reason: null },
  { at: iso(40), kind: 'other', who: 'token-verify-policies', env: 'stg', account: 'ubuntu', role: 'list', serial: null, result: 'issued', reason: null },
  { at: iso(50), kind: 'person', who: null, env: 'dev', account: 'ubuntu', role: 'dev-ubuntu', serial: null, result: 'issued', reason: null },
  { at: iso(60), kind: 'other', who: JWT, env: 'dev', account: null, role: 'dev-gwtest', serial: null, result: 'issued', reason: null },
  { at: iso(3 * 24 * 60), kind: 'person', who: 'ops@example.com', env: 'dev', account: 'ubuntu', role: 'dev-ubuntu', serial: 'aabbccdd00112233', result: 'issued', reason: null },
]
const OK = {
  state: 'ok', reasons: [], notes: [], written_at: iso(0), host: 'idp-host', window_days: 14, files_read: 15, lines_read: 2600,
  written_age_seconds: 20, stale_after_seconds: 300, events: EVENTS,
}

// gw 접속 기록(2단계) — 기본은 '연결 전'(1단계 시험들이 그대로 돌게)
const GW_OFF = {
  state: 'off', reasons: ['아직 연결 전'], notes: [], written_at: null, host: null, window_days: null, files_read: null, lines_read: null,
  written_age_seconds: null, stale_after_seconds: null, events: [], reports: null, gws: [], gws_known: false, reporting: 0, unlinked: 0,
  inventory: { state: 'skipped', reason: null },
}

// 주소마다 답 — /api/access-log(발급 기록) · /api/access-log/gw-logins(gw 접속 기록)
function serve(reply: object | number | 'fail', gwReply: object | number | 'fail' = GW_OFF) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const r = String(url).endsWith('/gw-logins') ? gwReply : reply
      if (r === 'fail') throw new TypeError('Failed to fetch')
      if (typeof r === 'number')
        return new Response(JSON.stringify({ detail: '운영자만 볼 수 있어요' }), { status: r, headers: { 'content-type': 'application/json' } })
      return new Response(JSON.stringify(r), { status: 200 })
    }),
  )
}

const rows = () => screen.queryAllByTestId('access-log-row').map((r) => within(r).getAllByRole('cell').map((c) => c.textContent))

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

test('ok — 사람 줄만 최신순, 이메일 기록 전 사람 · 개인 계정 · 번호 없음 · 여러 줄 까닭을 읽기 좋게, 설명은 "인증서를 받은 기록"', async () => {
  serve(OK)
  render(<AccessLog />)
  expect(await screen.findByText(/금고 기록 · 최근 14일 · 방금 기록 · 파일 15개 · 읽은 줄 2,600/)).toBeInTheDocument()
  expect(rows().map((r) => r.slice(1, 6))).toEqual([
    ['dev@example.com', 'prod', 'ubuntu', '거부1 error occurred: * permission denied', '11d1bda82b498807'], // 줄바꿈 · 탭은 한 줄로
    ['dev@example.com', 'dev', '개인 계정', '발급', '번호 없음(설정 전)'], // 계정이 비면 *-gw 역할 = 개인 gw 계정
    ['사람(이메일 기록 전)', 'dev', 'ubuntu', '발급', '번호 없음(설정 전)'], // 사람인데 누가 없음
    ['사람(이메일 기록 전)', 'dev', '—', '발급', '번호 없음(설정 전)'], // jwt-<16진수> 는 사람으로 · 이상한 역할(dev-gwtest)은 그대로 — 개인 계정으로 짐작 안 함
    ['ops@example.com', 'dev', 'ubuntu', '발급', 'aabbccdd00112233'],
  ])
  expect(rows().every((r) => /^\d{4}-\d\d-\d\d \d\d:\d\d$/.test(r[0] ?? ''))).toBe(true) // 나노초 시각도 읽힘
  expect(rows().every((r) => r[6] === '연결 전')).toBe(true) // gw 접속 기록이 아직 없으면 빈 칸이 아니라 '연결 전'
  expect(screen.getByText(/인증서\(도장\)를 받은 기록/)).toBeInTheDocument()
  expect(screen.getByText(/받았다고 들어간 건 아니에요/)).toBeInTheDocument()
  expect(screen.getByText(/수집기가 gw 접속 기록을 올린 적이 없어요/)).toBeInTheDocument()
})

test('기계 · 시험/관리 토큰은 접어 두고, 켜면 보임', async () => {
  serve(OK)
  render(<AccessLog />)
  await screen.findAllByTestId('access-log-row')
  fireEvent.click(screen.getByLabelText(/기계 · 시험\/관리 토큰도 보기 \(2\)/))
  expect(rows().map((r) => r[1])).toEqual([
    'dev@example.com', 'dev@example.com', 'runner기계', 'token-verify-policies시험/관리 토큰', '사람(이메일 기록 전)', '사람(이메일 기록 전)', 'ops@example.com',
  ])
})

test('거르기 — 기간(오늘) · 환경 · 사람(이메일 기록 전도 한 사람으로 고름)', async () => {
  // '오늘' 은 보는 사람 시간대의 자정부터 — 자정 근처에 돌아도 흔들리지 않게 시각만 고정(타이머는 그대로)
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 28, 15, 0))
  const fixed = EVENTS.map((e, i) => ({ ...e, at: new Date(2026, 9, 28 - (i === 6 ? 3 : 0), 14, 55 - i).toISOString() }))
  serve({ ...OK, events: fixed })
  render(<AccessLog />)
  await screen.findAllByTestId('access-log-row')
  fireEvent.click(within(screen.getByRole('radiogroup', { name: '기간 필터' })).getByRole('radio', { name: '오늘' }))
  expect(rows().map((r) => r[2])).toEqual(['prod', 'dev', 'dev', 'dev']) // 3일 전 기록은 빠짐
  fireEvent.click(within(screen.getByRole('radiogroup', { name: '기간 필터' })).getByRole('radio', { name: '14일' }))
  fireEvent.click(within(screen.getByRole('radiogroup', { name: '환경 필터' })).getByRole('radio', { name: 'prod' }))
  expect(rows().map((r) => r[2])).toEqual(['prod'])
  fireEvent.click(within(screen.getByRole('radiogroup', { name: '환경 필터' })).getByRole('radio', { name: '전체' }))
  fireEvent.click(within(screen.getByRole('radiogroup', { name: '사람 필터' })).getByRole('radio', { name: '사람(이메일 기록 전)' }))
  expect(rows().map((r) => r[1])).toEqual(['사람(이메일 기록 전)', '사람(이메일 기록 전)'])
})

test('운영 모양(93건: dev 74 · stg 8 · prod 11, 거부 26) — 최신순이고 거르기가 맞음', async () => {
  const envs = [...Array(74).fill('dev'), ...Array(8).fill('stg'), ...Array(11).fill('prod')]
  const many = envs.map((env, i) => ({
    at: iso(i * 37), kind: 'person', who: `user${i % 5}@example.com`, env, account: 'ubuntu', role: `${env}-ubuntu`,
    serial: i < 40 ? (0x1000 + i).toString(16).padStart(16, '0') : null, result: i % 93 < 26 ? 'denied' : 'issued', reason: i % 93 < 26 ? 'permission denied' : null,
  }))
  serve({ ...OK, events: many })
  render(<AccessLog />)
  await screen.findAllByTestId('access-log-row')
  expect(rows()).toHaveLength(93)
  const times = screen.getAllByTestId('access-log-row').map((r) => within(r).getAllByRole('cell')[0].getAttribute('title') ?? '')
  expect([...times].sort().reverse()).toEqual(times) // 최신순
  fireEvent.click(within(screen.getByRole('radiogroup', { name: '환경 필터' })).getByRole('radio', { name: 'stg' }))
  expect(rows()).toHaveLength(8)
  fireEvent.click(within(screen.getByRole('radiogroup', { name: '환경 필터' })).getByRole('radio', { name: 'prod' }))
  expect(rows()).toHaveLength(11)
  expect(screen.queryAllByText('거부').length + screen.queryAllByText('발급').length).toBe(11)
  fireEvent.click(within(screen.getByRole('radiogroup', { name: '환경 필터' })).getByRole('radio', { name: 'dev' }))
  expect(screen.queryAllByText('거부')).toHaveLength(26) // 거부 26건은 모두 dev(정책 시험)
})

test('읽었고 0건이면 "최근 N일 접속 없음", 기계 기록만 있으면 접어 둔 것을 알림 — 빈 표만 두지 않음', async () => {
  serve({ ...OK, events: [] })
  const { unmount } = render(<AccessLog />)
  expect(await screen.findByText('최근 14일 접속 없음')).toBeInTheDocument()
  unmount()
  serve({ ...OK, events: [EVENTS[2]] })
  render(<AccessLog />)
  expect(await screen.findByText('사람이 받은 기록은 없어요 — 기계 · 시험/관리 토큰 1건은 접어 두었어요')).toBeInTheDocument()
})

test.each([
  [{ state: 'unknown', reasons: ['못 봄 — 요약 파일이 없어요(IdP 서버가 아직 안 만들었거나 지워짐)'] }, /못 봄 — 요약 파일이 없어요.*표를 숨겼어요/],
  [{ state: 'unknown', reasons: ['못 봄 — 금고 기록이 비어 있어요(IdP 가 읽은 감사 기록이 0줄)'] }, /못 봄 — 금고 기록이 비어 있어요/],
  [{ state: 'unknown', reasons: ['멈춤 — 요약 기록이 10분째 그대로예요(IdP 쪽 타이머 확인)'] }, /멈춤 — 요약 기록이 10분째/],
  [{ state: 'off', reasons: ['아직 연결 전'] }, /아직 연결 전이에요 — 수집기가 접속 기록을/],
  [{ state: 'no_identity', reasons: [] }, /로그인 정보\(그룹\)를 몰라 보여 줄 수 없어요/],
])('못 봄 · 멈춤 · 연결 전 · 누군지 모름 — 표 대신 까닭(%#)', async (extra, text) => {
  serve({ ...OK, events: [], ...extra })
  render(<AccessLog />)
  expect(await screen.findByText(text)).toBeInTheDocument()
  expect(screen.queryByRole('table')).toBeNull()
  expect(screen.queryByText(/접속 없음/)).toBeNull() // 못 봄을 '접속 없음' 으로 말하지 않음
})

test('운영자가 아니면(403) "운영자만", 못 닿으면 "불러오지 못했어요"', async () => {
  serve(403)
  const { unmount } = render(<AccessLog />)
  expect(await screen.findByText(/운영자만 볼 수 있어요 — 접속 기록은 운영자\(server-admin\)만 봐요/)).toBeInTheDocument()
  unmount()
  serve('fail')
  render(<AccessLog />)
  expect(await screen.findByText(/접속 기록을 불러오지 못했어요/)).toBeInTheDocument()
  expect(screen.queryByRole('table')).toBeNull()
})

// ── 2단계: 들어간 gw · 시각 — gw 가 보고한 접속을 인증서 번호로 발급 줄에 이어 붙임 ─────────────

const issued = (min: number, who: string | null, env: string, account: string | null, serial: string | null, extra = {}) => ({
  at: iso(min), kind: 'person', who, env, account, role: account ? `${env}-${account}` : `${env}-gw`, serial, result: 'issued', reason: null, ...extra,
})
const ISSUED = [
  issued(10, 'ops@example.com', 'dev', 'ubuntu', '776cb41cedacd9d8'), // 5번 들어감
  issued(11, 'dev@example.com', 'stg', null, '0A:0B:0C:0D:0E:0F:10:11'), // 번호 모양이 달라도(콜론 · 대문자) 같은 번호
  issued(12, 'dev@example.com', 'dev', 'ubuntu', '1111222233334444'), // 받았지만 보고된 접속 없음
  issued(13, 'dev@example.com', 'prod', 'ubuntu', '5555666677778888', { result: 'denied', reason: 'permission denied' }),
  issued(14, 'ops@example.com', 'dev', 'ubuntu', null), // 번호 적기 전
  issued(14.5, 'dev@example.com', 'prod', 'ubuntu', null, { result: 'denied', reason: 'permission denied' }), // 거부 · 번호 없음
  issued(15, 'runner', 'dev', 'appuser', '9999aaaabbbbcccc', { kind: 'machine' }), // 기계 — 접어 둠
]
const login = (min: number, gw: string, account: string, serial: string, extra = {}) => ({
  at: iso(min), gw, account, kind: 'person', who: 'ops@example.com', serial, issued_at: null, env: null, role: null, ...extra,
})
const LOGINS = [
  ...[1, 2, 3, 4, 5].map((m) => login(m, 'gw-shop-dev', 'ubuntu', '776cb41cedacd9d8')),
  login(6, 'gw-shop-stg', 'dev1', '0a0b0c0d0e0f1011', { who: 'dev@example.com' }),
  login(7, 'gw-shop-dev', 'appuser', '9999aaaabbbbcccc', { kind: 'machine', who: 'runner' }),
  login(8, 'gw-shop-dev', 'ubuntu', 'dead0000beef1111'), // 발급 기록 없음
  login(9, 'gw-shop-dev', 'appuser', 'feed0000feed2222', { kind: 'machine', who: 'runner' }), // 발급 기록 없음 · 기계
  login(16 * 24 * 60, 'gw-shop-stg', 'dev1', 'cafe0000cafe3333', { who: 'dev@example.com', issued_at: iso(16 * 24 * 60 + 5), env: 'stg' }),
]
// 출입증 이름(gw)은 관리자가 지은 별칭 — 금고 목록과 잇는 건 gw 가 적어 보낸 env · service 뿐
const report = (gw: string | null, env: string | null, service: string | null, state: string, link: string, reason: string | null = null, min: number | null = 1) => ({
  gw, host: gw ? `${gw}-host` : null, env, service, state, reason, last_report_at: min == null ? null : iso(min),
  age_seconds: min == null ? null : min * 60, every_seconds: min == null ? null : 300, link,
})
const GWS = [
  report('gw-alpha', 'dev', 'shop', 'ok', 'listed'),
  report('gw-beta', 'stg', 'shop', 'stale', 'listed', '보고 끊김 — 마지막 보고가 16분 전이에요(gw 타이머 · 출입증 확인)', 16),
  report('gw-lab', 'dev', 'lab', 'unknown', 'not_listed', '못 봄 — gw 가 자기 접속 기록을 못 읽음: 권한 없음', 2),
  report('gw-new', null, null, 'ok', 'unlinked'), // trust 전 — env · service 를 안 보냄
  report(null, 'prod', 'pay', 'maybe_silent', 'listed', '보고 안 함일 수 있음 — 목록과 못 잇는 보고 1개', null),
]
const GW = {
  ...GW_OFF, state: 'ok', reasons: [], written_at: iso(0), host: 'idp-host', window_days: 14, files_read: 15, lines_read: 2600,
  written_age_seconds: 20, stale_after_seconds: 300, events: LOGINS, reports: 30, gws: GWS, gws_known: true, reporting: 2, unlinked: 1,
  inventory: { state: 'ok', reason: null },
}
const ISSUED_OK = { ...OK, events: ISSUED }
const gwCell = (i: number) => rows()[i][6]
const orphanRows = () => screen.queryAllByTestId('gw-orphan-row').map((r) => within(r).getAllByRole('cell').map((c) => c.textContent))

test('발급 줄마다 그 인증서로 들어간 gw · 시각 · 계정 — 여러 번이면 횟수, 번호 없음 · 보고된 접속 없음 · 거부는 따로', async () => {
  serve(ISSUED_OK, GW)
  render(<AccessLog />)
  await screen.findAllByTestId('gw-logins-cell')
  const first = within(screen.getAllByTestId('access-log-row')[0]).getByTestId('gw-logins-cell')
  expect(first.textContent).toMatch(/^5번/)
  expect(within(first).getAllByText(/^gw-shop-dev · \d{4}-\d\d-\d\d \d\d:\d\d · ubuntu$/)).toHaveLength(3) // 3줄까지만
  expect(first.textContent).toMatch(/외 2번$/)
  expect(gwCell(1)).toMatch(/^gw-shop-stg · \d{4}-\d\d-\d\d \d\d:\d\d · dev1$/) // 콜론 · 대문자 번호도 이어짐, 한 번이면 횟수 없음
  expect(gwCell(2)).toBe('보고된 접속 없음') // '안 들어감' 이 아니라 '보고된 것이 없음'
  expect(gwCell(3)).toBe('—') // 거부된 인증서
  expect(gwCell(4)).toBe('번호 없어 못 이음')
  expect(gwCell(5)).toBe('—') // 거부는 번호가 없어도 '못 이음' 이 아니라 쓸 인증서가 없음
  expect(rows()).toHaveLength(6) // 기계 줄(과 그 접속)은 접어 둠
})

test('발급 기록과 못 이은 접속은 따로 — 기계 접속은 접어 두고, 기계 줄에 이어진 접속은 그쪽에', async () => {
  serve(ISSUED_OK, GW)
  render(<AccessLog />)
  expect(await screen.findByText('발급 기록과 못 이은 접속 — 번호 기록 설정 전에 받았거나 14일 넘은 인증서')).toBeInTheDocument()
  expect(orphanRows().map((r) => [r[1], r[2], r[3], r[4], r[5]])).toEqual([
    ['gw-shop-dev', 'ubuntu', 'ops@example.com', 'dead0000beef1111', '못 이음(번호 기록 설정 전 · 14일 넘음 등)'],
  ]) // 16일 전 접속은 기간(14일) 밖
  fireEvent.click(within(screen.getByRole('radiogroup', { name: '기간 필터' })).getByRole('radio', { name: '오늘' }))
  fireEvent.click(within(screen.getByRole('radiogroup', { name: '기간 필터' })).getByRole('radio', { name: '14일' }))
  fireEvent.click(screen.getByLabelText(/기계 · 시험\/관리 토큰도 보기 \(2\)/)) // 발급 줄 기계 1 + 발급 기록 없는 기계 접속 1
  expect(orphanRows().map((r) => r[4])).toEqual(['dead0000beef1111', 'feed0000feed2222']) // 기계 줄에 이어진 9999… 는 여기 없음
  expect(rows()).toHaveLength(7)
  expect(gwCell(6)).toMatch(/^gw-shop-dev · .* · appuser$/)
})

test('발급 기록 없는 접속의 "누가" 에도 이름표 이름', async () => {
  serve({ ...ISSUED_OK, names: { state: 'ok', reasons: [], notes: [], people: { 'ops@example.com': { name: 'Ops Person', active: true } } } }, GW)
  render(<AccessLog />)
  await screen.findAllByTestId('gw-orphan-row')
  expect(orphanRows()[0][3]).toBe('ops@example.comOps Person')
})

const reportRows = () =>
  screen.getAllByTestId('gw-report-row').map((r) => within(r).getAllByRole('cell').map((c) => c.textContent)).map((c) => [c[0], c[1], c[3]])

test('gw 보고 상태 — 보고 중 · 보고 끊김 · 못 봄 · 보고 안 함일 수 있음, 금고 목록과 이은 결과(환경/서비스)', async () => {
  serve(ISSUED_OK, GW)
  render(<AccessLog />)
  await screen.findAllByTestId('gw-report-row')
  expect(reportRows()).toEqual([
    ['gw-alpha', '보고 중', 'dev/shop'],
    ['gw-beta', '보고 끊김', 'stg/shop'],
    ['gw-lab', '못 봄', 'dev/lab — 목록에 없음'],
    ['gw-new', '보고 중', '목록과 못 이음'],
    ['—', '보고 안 함일 수 있음', 'prod/pay'], // 목록에만 있음 — 못 잇는 보고(gw-new)가 그 gw 일 수 있어 단정 안 함
  ])
  expect(screen.getByText('보고 안 함일 수 있음 — 목록과 못 잇는 보고 1개')).toBeInTheDocument()
  expect(screen.getByTestId('gw-unlinked').textContent).toBe('목록과 못 이음 — gw-new (환경 · 서비스를 안 보냄 — trust 전이거나 옛 꾸러미)')
  expect(screen.getAllByText('5분마다 보고')).toHaveLength(2)
  expect(screen.getByText(/gw 접속 기록 · 최근 14일 · 방금 기록 · 보고 중 2\/5대/)).toBeInTheDocument()
})

test('못 잇는 보고가 없으면 목록에만 있는 gw 는 "보고 안 함" 으로 단정', async () => {
  const reason = '보고 안 함 — 금고 목록에 있는 gw 인데 이어지는 보고가 없어요(gw 보고 켜기 · trust 확인)'
  serve(ISSUED_OK, { ...GW, gws: [GWS[0], report(null, 'prod', 'pay', 'silent', 'listed', reason, null)], reporting: 1, unlinked: 0 })
  render(<AccessLog />)
  await screen.findAllByTestId('gw-report-row')
  expect(reportRows()).toEqual([['gw-alpha', '보고 중', 'dev/shop'], ['—', '보고 안 함', 'prod/pay']])
  expect(screen.getByText(reason)).toBeInTheDocument()
  expect(screen.queryByTestId('gw-unlinked')).toBeNull()
})

test('금고 목록이 꺼져 있으면 "보고 안 하는 gw 가 있는지 몰라요" — 보낸 환경/서비스는 보이되 "목록 모름"', async () => {
  const reason = '금고 목록(서버 탭)에 연결 전이라 보고 안 하는 gw 가 있는지 몰라요'
  const gws = GWS.filter((g) => g.gw).map((g) => (g.link === 'unlinked' ? g : { ...g, link: 'unknown' }))
  serve(ISSUED_OK, { ...GW, gws, inventory: { state: 'off', reason } })
  render(<AccessLog />)
  expect(await screen.findByText(reason)).toBeInTheDocument()
  expect(reportRows().map((r) => r[2])).toEqual(['dev/shop — 목록 모름', 'stg/shop — 목록 모름', 'dev/lab — 목록 모름', '목록과 못 이음'])
})

test.each([
  [{ state: 'unknown', reasons: ['못 봄 — 요약 파일이 없어요(IdP 서버가 아직 안 만들었거나 지워짐)'], events: [], gws: [] }, '못 봄', /못 봄 — 요약 파일이 없어요.*들어간 gw 칸도 '못 봄' 으로 두었어요/],
  [{ state: 'unknown', reasons: ['멈춤 — 요약 기록이 10분째 그대로예요(IdP 쪽 타이머 확인)'], events: [], gws: [] }, '못 봄', /멈춤 — 요약 기록이 10분째/],
])('gw 접속 기록을 못 보면 칸은 "못 봄", 보고 상태 · 발급 기록 없는 접속도 안 그림(%#)', async (extra, cell, text) => {
  serve(ISSUED_OK, { ...GW, ...extra })
  render(<AccessLog />)
  expect(await screen.findByText(text)).toBeInTheDocument()
  expect(rows().every((r) => r[6] === cell)).toBe(true)
  expect(screen.queryAllByTestId('gw-report-row')).toHaveLength(0)
  expect(screen.queryAllByTestId('gw-orphan-row')).toHaveLength(0)
  expect(screen.queryByText(/보고된 접속 없음|들어온 기록이 없어요/)).toBeNull() // 못 봄을 '안 들어옴' 으로 말하지 않음
})

test('들어간 기록이 0번이면 보고 중인 gw 만큼만 말함 — 보고 안 하는 gw 는 모른다고', async () => {
  serve(ISSUED_OK, { ...GW, events: [] })
  const { unmount } = render(<AccessLog />)
  expect(await screen.findByText('보고 중인 gw 2대에는 최근 14일 들어온 기록이 없어요 — 보고 안 하는(끊긴 · 못 본) gw 3대는 몰라요')).toBeInTheDocument()
  unmount()
  serve(ISSUED_OK, { ...GW, events: [], gws: [], reporting: 0, unlinked: 0, inventory: { state: 'off', reason: '금고 목록 연결 전' } })
  render(<AccessLog />)
  expect(await screen.findByText('보고 중인 gw 가 없어 들어간 기록을 볼 수 없어요')).toBeInTheDocument()
  expect(screen.getByText(/아직 보고한 gw 가 없어요 — 그래서 들어간 기록을 볼 수 없어요/)).toBeInTheDocument()
  expect(gwCell(2)).toBe('보고하는 gw 없음') // '보고된 접속 없음' 도 아님 — 볼 수 있는 gw 가 없음
  expect(screen.queryByText(/최근 \d+일 접속 없음|보고된 접속 없음/)).toBeNull()
})

test('파일에 gw 마다 상태가 없으면 "보고 안 하는 gw 를 가릴 수 없어요"', async () => {
  serve(ISSUED_OK, { ...GW, gws: [], gws_known: false, reporting: 0, unlinked: 0 })
  render(<AccessLog />)
  expect(await screen.findByText(/gw 마다 보고 상태가 파일에 없어요 — 보고 안 하는 gw 를 가릴 수 없어요/)).toBeInTheDocument()
  expect(screen.queryAllByTestId('gw-report-row')).toHaveLength(0)
})

test('발급 기록을 못 보면 gw 접속을 이어 붙이지 않고 따로 — 발급 표는 숨김', async () => {
  serve({ ...OK, state: 'unknown', reasons: ['못 봄 — 요약 파일이 없어요'], events: [] }, GW)
  render(<AccessLog />)
  expect(await screen.findByText('들어간 gw · 시각 — 발급 기록을 못 봐서 이어 붙이지 못했어요')).toBeInTheDocument()
  expect(rows()).toHaveLength(0)
  expect(orphanRows()).toHaveLength(7) // 사람 접속 8번 중 기간(14일) 안 7번 — 기계 2번은 접어 둠
  expect(screen.getByText('기계 · 시험/관리 토큰 접속 2번은 접어 두었어요.')).toBeInTheDocument()
  expect(orphanRows()[0][5]).toBe('발급 기록을 못 봐서 못 이음')
})

test.each([
  ['못 봄', { state: 'unknown', reasons: ['못 봄 — 요약 파일이 없어요'] }],
  ['연결 전', { state: 'off', reasons: ['아직 연결 전'] }],
])('발급 기록을 못 보면(%s) 못 이은 까닭도 "못 봐서" — 번호 기록 설정 전 · 14일 넘음으로 보이지 않음', async (_, s) => {
  serve({ ...OK, ...s, events: [] }, GW)
  render(<AccessLog />)
  expect(await screen.findByText('들어간 gw · 시각 — 발급 기록을 못 봐서 이어 붙이지 못했어요')).toBeInTheDocument()
  expect(orphanRows().map((r) => r[5])).toEqual(Array(7).fill('발급 기록을 못 봐서 못 이음'))
})

test('gw 접속 기록만 못 불러오면 그 까닭 — 칸은 "못 봄"', async () => {
  serve(ISSUED_OK, 'fail')
  render(<AccessLog />)
  expect(await screen.findByText(/gw 접속 기록을 불러오지 못했어요 — Failed to fetch/)).toBeInTheDocument()
  await screen.findAllByTestId('access-log-row')
  expect(rows().every((r) => r[6] === '못 봄')).toBe(true)
})

// '누가' 칸 — 이름표(Authentik)에서 찾으면 이메일 옆에 이름. 키는 이메일 소문자. 못 찾거나 이름표를 모르면 이메일만
const NAMED_EVENTS = [
  { at: iso(5), kind: 'person', who: 'Dev@Example.com', env: 'dev', account: 'ubuntu', role: 'dev-ubuntu', serial: 'a1', result: 'issued', reason: null },
  { at: iso(6), kind: 'person', who: 'gone@example.com', env: 'dev', account: 'ubuntu', role: 'dev-ubuntu', serial: 'a2', result: 'issued', reason: null },
  { at: iso(7), kind: 'person', who: 'nobody@example.com', env: 'dev', account: 'ubuntu', role: 'dev-ubuntu', serial: 'a3', result: 'issued', reason: null },
]
const NAMES = {
  state: 'ok', reasons: [], notes: [],
  people: { 'dev@example.com': { name: 'Dev Person', active: true }, 'gone@example.com': { name: 'Left Company', active: false } },
}

test('이름표가 있으면 이메일 옆에 이름(대소문자 달라도) · 비활성 표시 · 못 찾으면 이메일만', async () => {
  serve({ ...OK, events: NAMED_EVENTS, names: NAMES })
  render(<AccessLog />)
  await screen.findAllByTestId('access-log-row')
  expect(rows().map((r) => r[1])).toEqual(['Dev@Example.comDev Person', 'gone@example.comLeft Company (비활성)', 'nobody@example.com'])
  expect(screen.getByText('Dev Person')).toHaveClass('person-name')
  expect(screen.getByText(/Left Company/)).toHaveClass('person-name--inactive')
  expect(screen.queryByTestId('names-note')).toBeNull()
  // 사람 거르기는 그대로 이메일로
  expect(screen.getByRole('radiogroup', { name: '사람 필터' })).toHaveTextContent('Dev@Example.com')
})

test.each([
  ['모름', { state: 'unknown', reasons: ['IdP 가 Authentik 을 못 읽음: group missing'], notes: [], people: {} }, '이름표를 못 읽어 이메일만 보여요 — IdP 가 Authentik 을 못 읽음: group missing'],
  ['연결 전', { state: 'off', reasons: [], notes: [], people: {} }, '이름표 연결 전이라 이메일만 보여요'],
])('이름표가 %s 이면 이메일만 + 작은 알림(오류 띠 없음)', async (_, names, note) => {
  serve({ ...OK, events: NAMED_EVENTS, names })
  render(<AccessLog />)
  await screen.findAllByTestId('access-log-row')
  expect(rows().map((r) => r[1])).toEqual(['Dev@Example.com', 'gone@example.com', 'nobody@example.com'])
  expect(screen.getByTestId('names-note')).toHaveTextContent(note)
  expect(screen.queryByRole('alert')).toBeNull()
})
