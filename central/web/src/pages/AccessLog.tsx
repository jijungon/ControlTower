import { useEffect, useMemo, useState } from 'react'
import { fetchAccessLog, ForbiddenError, type AccessEvent, type AccessLog as AccessLogData } from '../api'
import GroupFilter from '../components/GroupFilter'
import PersonName, { findName } from '../components/PersonName'
import SectionHead, { fmtTime, runAll } from '../components/SectionHead'

// 접속 기록 — 누가 · 언제 · 어느 환경에 · 어떤 계정으로 들어갈 인증서(도장)를 받았나(금고 기록). 운영자만 · 보기 전용.
// '서버에 실제로 들어간 기록' 이 아니다 — 인증서는 30분~1시간 쓸 수 있고 여러 번 쓰거나 안 쓸 수도 있다.
// 어느 gw · 서버인지는 금고 기록에 없다(환경 + 계정만) — 2단계(gw 접속 기록)부터.
// '못 봤다' 를 '아무도 안 들어왔다' 로 보이지 않는다 — 못 봄이면 표 대신 까닭을 보인다.

const PERIODS = [
  ['today', '오늘'],
  ['7', '7일'],
  ['14', '14일'],
] as const
type Period = (typeof PERIODS)[number][0]

const RESULT_LABEL: Record<string, string> = { issued: '발급', denied: '거부' }
const KIND_LABEL: Record<AccessEvent['kind'], string> = { person: '사람', machine: '기계', other: '시험/관리 토큰' }
const NO_EMAIL = '사람(이메일 기록 전)'
// 이메일을 적기 전(10-27 전) 사람 로그인은 금고에 'jwt-<긴 16진수>' 이름으로만 남았다 — 사람으로 본다
const JWT_NAME = /^jwt-[0-9a-f]{32,}$/

// 금고 시각은 나노초까지 올 수 있다 — 브라우저마다 읽는 자릿수가 달라 밀리초로 잘라 읽는다
function at(iso: string): string {
  return iso.replace(/(\.\d{3})\d+/, '$1')
}

// 화면에 보일 모양 — 이메일 기록 전 사람(누가 없음 · jwt-…)은 사람으로, 이름은 '사람(이메일 기록 전)'
type Row = AccessEvent & { kindShown: AccessEvent['kind']; whoShown: string }
function toRow(e: AccessEvent): Row {
  if (e.who && JWT_NAME.test(e.who)) return { ...e, kindShown: 'person', whoShown: NO_EMAIL }
  if (!e.who) return { ...e, kindShown: e.kind, whoShown: e.kind === 'person' ? NO_EMAIL : '이름 없음' }
  return { ...e, kindShown: e.kind, whoShown: e.who }
}

function since(p: Period, now: Date): number {
  if (p === 'today') {
    const d = new Date(now)
    d.setHours(0, 0, 0, 0)
    return d.getTime()
  }
  return now.getTime() - Number(p) * 24 * 3600 * 1000
}

function ago(sec: number | null): string {
  if (sec == null) return '기록 시각 모름'
  if (sec < 60) return '방금 기록'
  const m = Math.floor(sec / 60)
  return m < 120 ? `${m}분 전 기록` : `${Math.floor(m / 60)}시간 전 기록`
}

// 계정이 비면 개인 gw 계정(*-gw 역할) — 그 밖에 빈 건 모름
function account(e: AccessEvent): string {
  if (e.account) return e.account
  return e.role?.endsWith('-gw') ? '개인 계정' : '—'
}

function Result({ e }: { e: AccessEvent }) {
  const label = RESULT_LABEL[e.result] ?? e.result
  return (
    <>
      <span className={'badge ' + (e.result === 'issued' ? 'badge--ok' : e.result === 'denied' ? 'badge--danger' : 'badge--muted')}>{label}</span>
      {/* 금고 까닭은 줄바꿈 · 탭이 섞여 온다("1 error occurred:\n\t* permission denied") — 한 줄로 */}
      {e.reason && <span className="muted access-log__reason">{e.reason.replace(/\s+/g, ' ').trim()}</span>}
    </>
  )
}

export default function AccessLog() {
  const [data, setData] = useState<AccessLogData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [forbidden, setForbidden] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [who, setWho] = useState('')
  const [env, setEnv] = useState('')
  const [period, setPeriod] = useState<Period>('14')
  const [others, setOthers] = useState(false)

  const load = () =>
    fetchAccessLog().then(
      (d) => {
        // 모양이 다른 답(예: 옛 API · 로그인 화면)을 그대로 그리면 화면이 통째로 죽는다 — '못 불러옴' 으로
        if (!d || typeof d.state !== 'string' || !Array.isArray(d.events)) return setErr('응답 모양이 이상해요')
        setData(d)
        setErr(null)
      },
      (e: Error) => (e instanceof ForbiddenError ? setForbidden(e.message) : setErr(e.message)),
    )

  useEffect(() => {
    load()
  }, [])

  // 사람 줄만 기본으로 — 기계 · 시험/관리 토큰은 접어 둠
  const all = useMemo(() => (data?.events ?? []).map(toRow), [data])
  const visible = useMemo(() => all.filter((e) => others || e.kindShown === 'person'), [all, others])
  const shown = useMemo(() => {
    const from = since(period, new Date())
    return visible.filter((e) => (!who || e.whoShown === who) && (!env || e.env === env) && new Date(at(e.at)).getTime() >= from)
  }, [visible, who, env, period])

  const people = useMemo(() => [...new Set(visible.map((e) => e.whoShown))].sort(), [visible])
  const envs = useMemo(() => [...new Set(all.map((e) => e.env))].sort(), [all])
  const otherCount = all.filter((e) => e.kindShown !== 'person').length
  const days = data?.window_days ?? 14

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">접속 기록</h1>
        <p className="page-sub">
          누가 · 언제 · 어느 환경에 · 어떤 계정으로 들어갈 <b>인증서(도장)를 받은 기록</b>이에요 — 서버에 실제로 들어간 기록이 아니에요.
          인증서는 30분~1시간 쓸 수 있어서 여러 번 쓰거나 안 쓸 수도 있고, 어느 gw · 서버인지는 금고 기록에 없어요(환경 + 계정만). 운영자만 봐요.
        </p>
      </div>

      <SectionHead
        title="인증서 발급 기록"
        sub={
          data?.state === 'ok'
            ? `금고 기록 · 최근 ${days}일 · ${ago(data.written_age_seconds)}` +
              (data.files_read != null ? ` · 파일 ${data.files_read}개` : '') +
              (data.lines_read != null ? ` · 읽은 줄 ${data.lines_read.toLocaleString()}` : '')
            : '금고 기록'
        }
        asOf={data?.written_at ? at(data.written_at) : null}
        onRefresh={() => runAll(setBusy, [load])}
        busy={busy}
        source="IdP 서버가 1분마다 금고 감사 기록을 요약 → 수집기가 읽어 올림"
      />

      {forbidden && <div className="card placeholder access-msg">{forbidden} — 접속 기록은 운영자(server-admin)만 봐요.</div>}
      {err && !forbidden && <div className="card placeholder access-msg">접속 기록을 불러오지 못했어요 — {err}</div>}
      {!data && !err && !forbidden && <div className="card placeholder access-msg">불러오는 중…</div>}

      {data?.state === 'off' && (
        <div className="card placeholder access-msg">아직 연결 전이에요 — 수집기가 접속 기록을 올린 적이 없어요.</div>
      )}
      {data?.state === 'no_identity' && (
        <div className="card placeholder access-msg access-msg--warn">
          로그인 정보(그룹)를 몰라 보여 줄 수 없어요 — 운영자만 보는 기록이라 막아 두었어요.
        </div>
      )}
      {data?.state === 'unknown' && (
        <div className="card placeholder access-msg access-msg--warn" role="status">
          {data.reasons.join(' · ') || '못 봄 — 이유 모름'}. 지금 기록으로 보이지 않게 표를 숨겼어요.
        </div>
      )}

      {data?.state === 'ok' && (
        <>
          <div className="toolbar access-log__filters">
            {/* 기간은 '전체' 가 없는 고르기라 GroupFilter 와 같은 모양으로 직접 */}
            <div className="seg" role="radiogroup" aria-label="기간 필터">
              <span className="seg-label">기간</span>
              {PERIODS.map(([v, label]) => (
                <button
                  key={v}
                  type="button"
                  role="radio"
                  aria-checked={period === v}
                  className={'seg-btn' + (period === v ? ' seg-btn--active' : '')}
                  onClick={() => setPeriod(v)}
                >
                  {label}
                </button>
              ))}
            </div>
            <GroupFilter label="환경" groups={envs} value={env} onChange={setEnv} />
            <GroupFilter label="사람" groups={people} value={who} onChange={setWho} />
            {otherCount > 0 && (
              <label className="access-log__machines">
                <input
                  type="checkbox"
                  checked={others}
                  onChange={(e) => {
                    setOthers(e.target.checked)
                    if (!e.target.checked) setWho('') // 고른 기계가 사라지면 빈 표가 되지 않게
                  }}
                />{' '}
                기계 · 시험/관리 토큰도 보기 ({otherCount})
              </label>
            )}
          </div>
          <div className="card">
            <table className="grid">
              <thead>
                <tr>
                  <th>시각</th>
                  <th>누가</th>
                  <th>환경</th>
                  <th>계정</th>
                  <th>결과</th>
                  <th>인증서 번호</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((e, i) => (
                  <tr key={`${e.at}|${e.who}|${e.env}|${i}`} data-testid="access-log-row">
                    <td className="mono" title={e.at}>{fmtTime(at(e.at))}</td>
                    <td title={e.who ?? ''}>
                      {e.whoShown === e.who ? e.who : <span className="muted">{e.whoShown}</span>}
                      {/* 이름표에서 찾으면 이메일 옆에 이름(소문자로 찾음) — 못 찾거나 이름표를 모르면 이메일만 */}
                      {e.whoShown === e.who && <PersonName {...findName(data.names, e.who)} />}
                      {e.kindShown !== 'person' && (
                        <span className="badge badge--muted access-log__kind">{KIND_LABEL[e.kindShown] ?? e.kindShown}</span>
                      )}
                    </td>
                    <td>{e.env}</td>
                    {/* 역할은 금고에 적힌 그대로(이상한 이름도) — 정해 둔 목록으로 거르지 않음 */}
                    <td className="mono" title={e.role ?? ''}>{account(e)}</td>
                    <td>
                      <Result e={e} />
                    </td>
                    <td className="mono muted">{e.serial ?? '번호 없음(설정 전)'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {shown.length === 0 && (
              <div className="placeholder access-msg">
                {data.events.length === 0
                  ? `최근 ${days}일 접속 없음`
                  : visible.length === 0
                    ? `사람이 받은 기록은 없어요 — 기계 · 시험/관리 토큰 ${otherCount}건은 접어 두었어요`
                    : '고른 조건에 맞는 기록이 없어요'}
              </div>
            )}
          </div>
          {data.notes.length > 0 && <p className="muted access-log__note">{data.notes.join(' · ')}</p>}
          {data.names && data.names.state !== 'ok' && (
            <p className="muted access-log__note" data-testid="names-note">
              {data.names.state === 'off' ? '이름표 연결 전이라 이메일만 보여요' : `이름표를 못 읽어 이메일만 보여요 — ${data.names.reasons.join(' · ') || '이유 모름'}`}
            </p>
          )}
          <p className="muted access-log__note">어느 gw · 서버로 들어갔는지는 2단계(gw 접속 기록)부터 보여요 — 지금은 금고가 인증서를 내준 기록이에요.</p>
        </>
      )}
    </div>
  )
}
