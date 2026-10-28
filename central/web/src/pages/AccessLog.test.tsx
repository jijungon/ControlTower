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

function serve(reply: object | number | 'fail') {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      if (reply === 'fail') throw new TypeError('Failed to fetch')
      if (typeof reply === 'number')
        return new Response(JSON.stringify({ detail: '운영자만 볼 수 있어요' }), { status: reply, headers: { 'content-type': 'application/json' } })
      return new Response(JSON.stringify(reply), { status: 200 })
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
  expect(rows().map((r) => r.slice(1))).toEqual([
    ['dev@example.com', 'prod', 'ubuntu', '거부1 error occurred: * permission denied', '11d1bda82b498807'], // 줄바꿈 · 탭은 한 줄로
    ['dev@example.com', 'dev', '개인 계정', '발급', '번호 없음(설정 전)'], // 계정이 비면 *-gw 역할 = 개인 gw 계정
    ['사람(이메일 기록 전)', 'dev', 'ubuntu', '발급', '번호 없음(설정 전)'], // 사람인데 누가 없음
    ['사람(이메일 기록 전)', 'dev', '—', '발급', '번호 없음(설정 전)'], // jwt-<16진수> 는 사람으로 · 이상한 역할(dev-gwtest)은 그대로 — 개인 계정으로 짐작 안 함
    ['ops@example.com', 'dev', 'ubuntu', '발급', 'aabbccdd00112233'],
  ])
  expect(rows().every((r) => /^\d{4}-\d\d-\d\d \d\d:\d\d$/.test(r[0] ?? ''))).toBe(true) // 나노초 시각도 읽힘
  expect(screen.getByText(/인증서\(도장\)를 받은 기록/)).toBeInTheDocument()
  expect(screen.getByText(/서버에 실제로 들어간 기록이 아니에요/)).toBeInTheDocument()
  expect(screen.getByText(/어느 gw · 서버로 들어갔는지는 2단계/)).toBeInTheDocument()
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
  [{ state: 'off', reasons: ['아직 연결 전'] }, /아직 연결 전이에요/],
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
