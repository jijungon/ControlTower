import { useEffect, useMemo, useState } from 'react'
import {
  fetchAccessLog,
  fetchGwLogins,
  fetchServerLogins,
  ForbiddenError,
  type AccessEvent,
  type AccessLog as AccessLogData,
  type GwLogin,
  type GwLogins,
  type GwReport,
  type ServerLogin,
  type ServerLogins,
  type ServerRead,
} from '../api'
import GroupFilter from '../components/GroupFilter'
import PersonName, { findName } from '../components/PersonName'
import SectionHead, { fmtTime, runAll } from '../components/SectionHead'

// 접속 기록 — 누가 · 언제 · 어느 환경에 · 어떤 계정으로 들어갈 인증서(도장)를 받았나(금고 기록). 운영자만 · 보기 전용.
// 인증서는 30분~1시간 쓸 수 있어 여러 번 쓰거나 안 쓸 수도 있다 → 실제로 들어간 gw · 시각은 gw 가 보고한 것(2단계)을,
// gw 뒤 서버에 들어간 서버 · 시각은 gw 가 서버 기록을 읽어 보낸 것(3단계)을 인증서 번호(serial)로 발급 줄에 이어 붙인다.
// 보고 안 하는 gw · 안 읽는 서버에 들어간 건 모른다 — 그래서 gw 마다 보고 상태 · 서버마다 읽기 상태를 같이 보인다.
// '못 봤다' 를 '아무도 안 들어왔다' 로 보이지 않는다 — 못 봄이면 표 대신 까닭, 이어 붙일 칸도 '못 봄'.

const PERIODS = [
  ['today', '오늘'],
  ['7', '7일'],
  ['14', '14일'],
] as const
type Period = (typeof PERIODS)[number][0]

const RESULT_LABEL: Record<string, string> = { issued: '발급', denied: '거부' }
const KIND_LABEL: Record<AccessEvent['kind'], string> = { person: '사람', machine: '기계', other: '시험/관리 토큰' }
const GW_STATE: Record<GwReport['state'], [string, string]> = {
  ok: ['보고 중', 'badge--ok'],
  stale: ['보고 끊김', 'badge--warn'],
  unknown: ['못 봄', 'badge--muted'],
  silent: ['보고 안 함', 'badge--warn'],
  maybe_silent: ['보고 안 함일 수 있음', 'badge--warn'],
}
const SRV_STATE: Record<ServerRead['state'], [string, string]> = {
  ok: ['읽는 중', 'badge--ok'],
  failed: ['못 읽음', 'badge--warn'],
  stale: ['끊김', 'badge--warn'],
  unknown: ['모름', 'badge--muted'],
  silent: ['안 읽음', 'badge--warn'],
  maybe_silent: ['안 읽음일 수 있음', 'badge--warn'],
}
const NO_EMAIL = '사람(이메일 기록 전)'
// 이메일을 적기 전(10-27 전) 사람 로그인은 금고에 'jwt-<긴 16진수>' 이름으로만 남았다 — 사람으로 본다
const JWT_NAME = /^jwt-[0-9a-f]{32,}$/
const MAX_LOGINS = 3 // 한 인증서에 붙여 보일 접속 줄 — 넘으면 '외 N번'

// 금고 시각은 나노초까지 올 수 있다 — 브라우저마다 읽는 자릿수가 달라 밀리초로 잘라 읽는다
function at(iso: string): string {
  return iso.replace(/(\.\d{3})\d+/, '$1')
}

// 인증서 번호 — 콜론 · 대소문자가 섞여 와도 같은 번호로 잇는다
function serialKey(s: string | null): string | null {
  return s ? s.replace(/:/g, '').toLowerCase() : null
}

// 화면에 보일 모양 — 이메일 기록 전 사람(누가 없음 · jwt-…)은 사람으로, 이름은 '사람(이메일 기록 전)'
type Shown<T> = T & { kindShown: AccessEvent['kind']; whoShown: string }
function toRow<T extends Pick<AccessEvent, 'who' | 'kind'>>(e: T): Shown<T> {
  if (e.who && JWT_NAME.test(e.who)) return { ...e, kindShown: 'person', whoShown: NO_EMAIL }
  if (!e.who) return { ...e, kindShown: e.kind, whoShown: e.kind === 'person' ? NO_EMAIL : '이름 없음' }
  return { ...e, kindShown: e.kind, whoShown: e.who }
}
type Row = Shown<AccessEvent>

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

const loginLine = (l: GwLogin) => `${l.gw} · ${fmtTime(at(l.at))} · ${l.account ?? '계정 모름'}`
const serverLine = (l: ServerLogin) => `${l.server} · ${fmtTime(at(l.at))} · ${l.account ?? '계정 모름'}`

// 발급 줄에 이어 붙이는 칸 — 들어간 gw(2단계) · 들어간 서버(3단계). 기록을 못 봤으면 '못 봄' · '모름' — 빈 칸을 '안 들어감' 으로 보이지 않는다.
type Feed = { state: string; known: boolean; live: number } | null // live = 보고 중인 gw · 읽는 중인 서버 수
type CellText = { unseen: string; none: string; noneTitle: string; noSource: string; noSourceTitle: string; testid: string }
const GW_TEXT: CellText = {
  unseen: '못 봄',
  none: '보고된 접속 없음',
  noneTitle: '보고 중인 gw 에는 이 인증서로 들어온 기록이 없어요 — 보고 안 하는(끊긴 · 못 본) gw 는 몰라요',
  noSource: '보고하는 gw 없음',
  noSourceTitle: '보고 중인 gw 가 하나도 없어 들어갔는지 알 수 없어요',
  testid: 'gw-logins-cell',
}
const SRV_TEXT: CellText = {
  unseen: '모름',
  none: '읽힌 접속 없음',
  noneTitle: '읽는 중인 서버에는 이 인증서로 들어온 기록이 없어요 — 안 읽는(못 읽은 · 끊긴 · 목록에만 있는) 서버는 몰라요',
  noSource: '읽는 서버 없음',
  noSourceTitle: '읽는 중인 서버가 하나도 없어 들어갔는지 알 수 없어요',
  testid: 'server-logins-cell',
}

function Linked<T extends { at: string }>({ e, feed, why, list, line, title, text }: {
  e: Row
  feed: Feed
  why: string
  list: T[]
  line: (l: T) => string
  title: (l: T) => string
  text: CellText
}) {
  if (feed?.state !== 'ok') return <span className="muted" title={why}>{feed?.state === 'off' ? '연결 전' : text.unseen}</span>
  if (list.length === 0 && e.result !== 'issued') return <span className="muted">—</span> // 거부 — 쓸 인증서가 없음
  if (!serialKey(e.serial))
    return <span className="muted" title="인증서 번호가 없는 기록(번호를 적기 전)이라 들어간 기록과 이을 수 없어요">번호 없어 못 이음</span>
  if (list.length === 0 && feed.known && feed.live === 0) return <span className="muted" title={text.noSourceTitle}>{text.noSource}</span>
  if (list.length === 0) return <span className="muted" title={text.noneTitle}>{text.none}</span>
  return (
    <div className="access-log__logins" data-testid={text.testid}>
      {list.length > 1 && <span className="badge badge--muted">{list.length}번</span>}
      {list.slice(0, MAX_LOGINS).map((l, i) => (
        <div key={`${l.at}|${i}`} className="mono" title={title(l)}>
          {line(l)}
        </div>
      ))}
      {list.length > MAX_LOGINS && <div className="muted">외 {list.length - MAX_LOGINS}번</div>}
    </div>
  )
}

// 인증서 번호 → 들어간 기록(최신순 그대로)
function bySerial<T extends { serial: string | null }>(list: T[]): Map<string, T[]> {
  const m = new Map<string, T[]>()
  for (const l of list) {
    const k = serialKey(l.serial)
    if (k) m.set(k, [...(m.get(k) ?? []), l])
  }
  return m
}

// 금고 목록과 이은 결과 — 잇는 건 gw 가 적어 보낸 환경/서비스뿐(출입증 이름으로 짐작하지 않음)
function ListCell({ g }: { g: Pick<GwReport, 'env' | 'service' | 'link'> }) {
  const where = g.env && g.service ? `${g.env}/${g.service}` : null
  if (g.link === 'listed') return <span className="mono">{where}</span>
  if (g.link === 'not_listed') return <span className="muted">{where} — 목록에 없음</span>
  if (g.link === 'unlinked')
    return (
      <span className="muted" title="gw 가 환경 · 서비스를 안 보냈어요(trust 전이거나 옛 꾸러미)">
        목록과 못 이음
      </span>
    )
  return <span className="muted">{where ? `${where} — 목록 모름` : '모름'}</span>
}

function GwReports({ gw }: { gw: GwLogins }) {
  if (!gw.gws_known)
    return <div className="placeholder access-msg access-msg--warn">gw 마다 보고 상태가 파일에 없어요 — 보고 안 하는 gw 를 가릴 수 없어요.</div>
  if (gw.gws.length === 0)
    return (
      <div className="placeholder access-msg access-msg--warn">
        {gw.inventory.state === 'ok' ? '보고하는 gw 도, 금고 목록에 있는 gw 도 없어요.' : '아직 보고한 gw 가 없어요 — 그래서 들어간 기록을 볼 수 없어요.'}
      </div>
    )
  return (
    <table className="grid">
      <thead>
        <tr>
          <th>gw</th>
          <th>보고</th>
          <th>마지막 보고</th>
          <th>금고 목록</th>
          <th>설명</th>
        </tr>
      </thead>
      <tbody>
        {gw.gws.map((g, i) => {
          const [label, cls] = GW_STATE[g.state] ?? [g.state, 'badge--muted']
          return (
            <tr key={`${g.gw ?? ''}|${g.env}|${g.service}|${i}`} data-testid="gw-report-row">
              <td className="mono" title={g.host ?? ''}>{g.gw ?? <span className="muted">—</span>}</td>
              <td>
                <span className={'badge ' + cls}>{label}</span>
              </td>
              <td className="mono" title={g.last_report_at ?? ''}>{g.last_report_at ? fmtTime(at(g.last_report_at)) : '—'}</td>
              <td>
                <ListCell g={g} />
              </td>
              <td className="muted">{g.reason ?? `${Math.round((g.every_seconds ?? 300) / 60)}분마다 보고`}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function ServerReads({ srv }: { srv: ServerLogins }) {
  if (!srv.servers_known)
    return <div className="placeholder access-msg access-msg--warn">서버마다 읽기 상태가 파일에 없어요 — 안 읽는 서버를 가릴 수 없어요.</div>
  if (srv.servers.length === 0)
    return (
      <div className="placeholder access-msg access-msg--warn">
        {srv.inventory.state === 'ok' ? '읽는 서버도, 금고 목록에 있는 서버도 없어요.' : '아직 서버 기록을 읽는 gw 가 없어요 — 그래서 들어간 기록을 볼 수 없어요.'}
      </div>
    )
  return (
    <table className="grid">
      <thead>
        <tr>
          <th>서버</th>
          <th>gw</th>
          <th>읽기</th>
          <th>마지막 읽기</th>
          <th>금고 목록</th>
          <th>설명</th>
        </tr>
      </thead>
      <tbody>
        {srv.servers.map((x, i) => {
          const [label, cls] = SRV_STATE[x.state] ?? [x.state, 'badge--muted']
          return (
            <tr key={`${x.gw ?? ''}|${x.env}|${x.service}|${x.server}|${i}`} data-testid="server-read-row">
              <td className="mono" title={x.host ?? ''}>{x.server}</td>
              <td className="mono">{x.gw ?? <span className="muted">—</span>}</td>
              <td>
                <span className={'badge ' + cls}>{label}</span>
              </td>
              <td className="mono" title={x.last_read_at ?? ''}>{x.last_read_at ? fmtTime(at(x.last_read_at)) : '—'}</td>
              <td>
                <ListCell g={x} />
              </td>
              {/* 못 읽은 까닭은 gw 가 적은 그대로 — 고쳐 쓰지 않는다 */}
              <td className="muted">{x.reason ?? 'gw 가 5분마다 읽어 보냄'}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function pickSerial<T>(m: Map<string, T[]>, serial: string | null): T[] {
  const k = serialKey(serial)
  return (k && m.get(k)) || []
}

// 발급 기록과 못 이은 접속(gw · 서버)의 '누가' 칸
function WhoCell({ l, names }: { l: Shown<{ who: string | null; kind: AccessEvent['kind'] }>; names: AccessLogData['names'] }) {
  return (
    <td title={l.who ?? ''}>
      {l.whoShown === l.who ? l.who : <span className="muted">{l.whoShown}</span>}
      {l.whoShown === l.who && <PersonName {...findName(names, l.who)} />}
      {l.kindShown !== 'person' && <span className="badge badge--muted access-log__kind">{KIND_LABEL[l.kindShown] ?? l.kindShown}</span>}
    </td>
  )
}

// 발급 기록과 못 이은 접속의 '발급' 칸 — 발급 기록을 못 봤으면 그렇게(번호 기록 설정 전 · 14일 넘음으로 보이지 않게)
function issuedText(l: { issued_at: string | null; env: string | null }, issuedOk: boolean): string {
  if (l.issued_at) return `${fmtTime(at(l.issued_at))}${l.env ? ` · ${l.env}` : ''}`
  return issuedOk ? '못 이음(번호 기록 설정 전 · 14일 넘음 등)' : '발급 기록을 못 봐서 못 이음'
}

// 서버 접속과 같은 인증서 번호의 gw 접속 — 있으면 '그 도장으로 이 gw 를 거쳐 서버에 들어감'. 서버 시각 바로 전의 것을 보인다.
function ViaGw({ l, feed, byserial }: { l: ServerLogin; feed: Feed; byserial: Map<string, GwLogin[]> }) {
  if (feed?.state !== 'ok') return <span className="muted">{feed?.state === 'off' ? 'gw 기록 연결 전' : 'gw 기록 못 봄'}</span>
  if (!serialKey(l.serial)) return <span className="muted">번호 없어 못 이음</span>
  const list = pickSerial(byserial, l.serial)
  if (list.length === 0)
    return (
      <span className="muted" title="같은 번호의 gw 접속 보고가 없어요 — gw 보고를 켜기 전이었거나 보고 안 하는 gw 일 수 있어요">
        gw 보고에 없음
      </span>
    )
  const t = new Date(at(l.at)).getTime()
  const g = list.find((x) => new Date(at(x.at)).getTime() <= t) ?? list[list.length - 1]
  return (
    <span className="mono" title={g.at} data-testid="server-via-gw">
      {g.gw} · {fmtTime(at(g.at))}
      {list.length > 1 && <span className="muted"> (같은 번호 {list.length}번)</span>}
    </span>
  )
}

export default function AccessLog() {
  const [data, setData] = useState<AccessLogData | null>(null)
  const [gw, setGw] = useState<GwLogins | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [gwErr, setGwErr] = useState<string | null>(null)
  const [srv, setSrv] = useState<ServerLogins | null>(null)
  const [srvErr, setSrvErr] = useState<string | null>(null)
  const [forbidden, setForbidden] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [who, setWho] = useState('')
  const [env, setEnv] = useState('')
  const [period, setPeriod] = useState<Period>('14')
  const [others, setOthers] = useState(false)

  const loadIssued = () =>
    fetchAccessLog().then(
      (d) => {
        // 모양이 다른 답(예: 옛 API · 로그인 화면)을 그대로 그리면 화면이 통째로 죽는다 — '못 불러옴' 으로
        if (!d || typeof d.state !== 'string' || !Array.isArray(d.events)) return setErr('응답 모양이 이상해요')
        setData(d)
        setErr(null)
      },
      (e: Error) => (e instanceof ForbiddenError ? setForbidden(e.message) : setErr(e.message)),
    )
  const loadGw = () =>
    fetchGwLogins().then(
      (d) => {
        if (!d || typeof d.state !== 'string' || !Array.isArray(d.events) || !Array.isArray(d.gws)) return setGwErr('응답 모양이 이상해요')
        setGw(d)
        setGwErr(null)
      },
      (e: Error) => (e instanceof ForbiddenError ? setForbidden(e.message) : setGwErr(e.message)),
    )
  const loadSrv = () =>
    fetchServerLogins().then(
      (d) => {
        if (!d || typeof d.state !== 'string' || !Array.isArray(d.events) || !Array.isArray(d.servers)) return setSrvErr('응답 모양이 이상해요')
        setSrv(d)
        setSrvErr(null)
      },
      (e: Error) => (e instanceof ForbiddenError ? setForbidden(e.message) : setSrvErr(e.message)),
    )
  const load = () => Promise.all([loadIssued(), loadGw(), loadSrv()])

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

  // gw 접속 → 인증서 번호별(최신순 그대로). 발급 줄에 없는 번호는 '발급 기록 없음'
  const logins = useMemo(() => (gw?.state === 'ok' ? gw.events : []), [gw])
  const byserial = useMemo(() => bySerial(logins), [logins])
  const issuedSerials = useMemo(() => new Set(all.map((e) => serialKey(e.serial)).filter(Boolean)), [all])
  const orphanAll = useMemo(
    () => logins.filter((l) => data?.state !== 'ok' || !issuedSerials.has(serialKey(l.serial))).map(toRow),
    [logins, issuedSerials, data],
  )
  // 발급 기록 없는 접속도 같은 거르기(사람만 · 기간 · 사람) — 환경은 발급 기록이 없으면 모르는 게 많아 안 거름
  const orphans = useMemo(() => {
    const from = since(period, new Date())
    return orphanAll.filter(
      (l) => (others || l.kindShown === 'person') && (!who || l.whoShown === who) && new Date(at(l.at)).getTime() >= from,
    )
  }, [orphanAll, others, who, period])

  // 서버 접속(3단계) → 인증서 번호별. 발급 줄에 없는 번호는 따로(같은 거르기)
  const srvLogins = useMemo(() => (srv?.state === 'ok' ? srv.events : []), [srv])
  const srvBySerial = useMemo(() => bySerial(srvLogins), [srvLogins])
  const srvOrphanAll = useMemo(
    () => srvLogins.filter((l) => data?.state !== 'ok' || !issuedSerials.has(serialKey(l.serial))).map(toRow),
    [srvLogins, issuedSerials, data],
  )
  const srvOrphans = useMemo(() => {
    const from = since(period, new Date())
    return srvOrphanAll.filter(
      (l) => (others || l.kindShown === 'person') && (!who || l.whoShown === who) && new Date(at(l.at)).getTime() >= from,
    )
  }, [srvOrphanAll, others, who, period])

  const people = useMemo(() => [...new Set(visible.map((e) => e.whoShown))].sort(), [visible])
  const envs = useMemo(() => [...new Set(all.map((e) => e.env))].sort(), [all])
  const otherCount = all.filter((e) => e.kindShown !== 'person').length
  const orphanOthers = orphanAll.filter((l) => l.kindShown !== 'person').length
  const srvOrphanOthers = srvOrphanAll.filter((l) => l.kindShown !== 'person').length
  const days = data?.window_days ?? 14
  const gwDays = gw?.window_days ?? 14
  const gwWhy = gwErr
    ? `gw 접속 기록을 불러오지 못했어요 — ${gwErr}`
    : !gw
      ? '불러오는 중…'
      : gw.reasons.join(' · ') || '못 봄 — 이유 모름'
  const notReporting = gw?.gws.filter((g) => g.state !== 'ok').length ?? 0
  const srvDays = srv?.window_days ?? 14
  // 서버 쪽은 파일을 못 봤으면 '모름'(+ 까닭) — 같은 판정이 주는 '못 봄 — …' 을 그 말로 바꿔 보인다
  const srvWhy = srvErr
    ? `서버 접속 기록을 불러오지 못했어요 — ${srvErr}`
    : !srv
      ? '불러오는 중…'
      : srv.reasons.map((r) => r.replace(/^못 봄 — /, '모름 — ')).join(' · ') || '모름 — 이유 모름'
  const notReading = srv?.servers.filter((x) => x.state !== 'ok').length ?? 0
  const gwFeed: Feed = gw && { state: gw.state, known: gw.gws_known, live: gw.reporting }
  const srvFeed: Feed = srv && { state: srv.state, known: srv.servers_known, live: srv.reading }

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">접속 기록</h1>
        <p className="page-sub">
          누가 · 언제 · 어느 환경에 · 어떤 계정으로 들어갈 <b>인증서(도장)를 받은 기록</b>이에요 — 받았다고 들어간 건 아니에요(30분~1시간 동안
          여러 번 쓰거나 안 쓸 수도 있어요). 실제로 <b>들어간 gw · 시각</b>은 gw 가 보고한 기록을, <b>gw 뒤 서버에 들어간 서버 · 시각</b>은 gw 가
          서버 기록을 읽어 보낸 것을 인증서 번호로 이어 붙였어요 — 보고 안 하는 gw · 안 읽는 서버에 들어간 건 안 보여요. 운영자만 봐요.
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
            {otherCount + orphanOthers + srvOrphanOthers > 0 && (
              <label className="access-log__machines">
                <input
                  type="checkbox"
                  checked={others}
                  onChange={(e) => {
                    setOthers(e.target.checked)
                    if (!e.target.checked) setWho('') // 고른 기계가 사라지면 빈 표가 되지 않게
                  }}
                />{' '}
                기계 · 시험/관리 토큰도 보기 ({otherCount + orphanOthers + srvOrphanOthers})
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
                  <th>들어간 gw · 시각</th>
                  <th>들어간 서버 · 시각</th>
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
                    <td>
                      <Linked e={e} feed={gwFeed} why={gwWhy} list={pickSerial(byserial, e.serial)} line={loginLine} title={(l) => l.at} text={GW_TEXT} />
                    </td>
                    <td>
                      <Linked
                        e={e}
                        feed={srvFeed}
                        why={srvWhy}
                        list={pickSerial(srvBySerial, e.serial)}
                        line={serverLine}
                        title={(l) => `${l.at} · ${l.gw ?? 'gw 모름'} 뒤${l.service ? ` · ${l.service}` : ''}`}
                        text={SRV_TEXT}
                      />
                    </td>
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
        </>
      )}

      {!forbidden && data?.state !== 'no_identity' && (
        <>
          <SectionHead
            title="들어간 gw · 시각"
            sub={
              gw?.state === 'ok'
                ? `gw 접속 기록 · 최근 ${gwDays}일 · ${ago(gw.written_age_seconds)}` +
                  (gw.gws_known ? ` · 보고 중 ${gw.reporting}/${gw.gws.length}대` : '')
                : 'gw 접속 기록'
            }
            asOf={gw?.written_at ? at(gw.written_at) : null}
            onRefresh={() => runAll(setBusy, [load])}
            busy={busy}
            source="gw 가 5분마다 자기 sshd 기록에서 '인증서로 들어온 줄' 을 금고에 보고 → IdP 서버가 1분마다 모아 요약 → 수집기가 읽어 올림"
          />
          {gwErr && <div className="card placeholder access-msg">gw 접속 기록을 불러오지 못했어요 — {gwErr}</div>}
          {!gw && !gwErr && <div className="card placeholder access-msg">불러오는 중…</div>}
          {gw?.state === 'off' && (
            <div className="card placeholder access-msg">아직 연결 전이에요 — 수집기가 gw 접속 기록을 올린 적이 없어요.</div>
          )}
          {gw?.state === 'unknown' && (
            <div className="card placeholder access-msg access-msg--warn" role="status" data-testid="gw-unknown">
              {gwWhy}. 들어간 gw 칸도 '못 봄' 으로 두었어요.
            </div>
          )}
          {gw?.state === 'ok' && (
            <>
              <h3 className="access-log__sub">gw 보고 상태</h3>
              <div className="card access-log__gws">
                <GwReports gw={gw} />
              </div>
              {gw.unlinked > 0 && (
                <p className="muted access-log__note" data-testid="gw-unlinked">
                  목록과 못 이음 — {gw.gws.filter((g) => g.link === 'unlinked').map((g) => g.gw).join(', ')} (환경 · 서비스를 안 보냄 — trust
                  전이거나 옛 꾸러미)
                </p>
              )}
              {gw.inventory.state !== 'ok' && gw.inventory.reason && <p className="muted access-log__note">{gw.inventory.reason}</p>}
              {gw.notes.length > 0 && <p className="muted access-log__note">{gw.notes.join(' · ')}</p>}

              <h3 className="access-log__sub">
                {data?.state === 'ok' ? '발급 기록과 못 이은 접속 — 번호 기록 설정 전에 받았거나 14일 넘은 인증서' : '들어간 gw · 시각 — 발급 기록을 못 봐서 이어 붙이지 못했어요'}
              </h3>
              {gw.events.length === 0 ? (
                <div className="card placeholder access-msg" data-testid="gw-no-logins">
                  {gw.reporting > 0
                    ? `보고 중인 gw ${gw.reporting}대에는 최근 ${gwDays}일 들어온 기록이 없어요` +
                      (notReporting > 0 ? ` — 보고 안 하는(끊긴 · 못 본) gw ${notReporting}대는 몰라요` : '')
                    : '보고 중인 gw 가 없어 들어간 기록을 볼 수 없어요'}
                </div>
              ) : orphans.length === 0 ? (
                <p className="muted access-log__note">
                  {orphanAll.length === 0
                    ? '없어요 — 모든 접속이 위 발급 기록에 이어 붙었어요.'
                    : `고른 조건에 맞는 것이 없어요(접어 둔 기계 · 시험/관리 토큰 포함 ${orphanAll.length}번).`}
                </p>
              ) : (
                <div className="card">
                  <table className="grid">
                    <thead>
                      <tr>
                        <th>들어간 시각</th>
                        <th>gw</th>
                        <th>계정</th>
                        <th>누가</th>
                        <th>인증서 번호</th>
                        <th>발급</th>
                      </tr>
                    </thead>
                    <tbody>
                      {orphans.map((l, i) => (
                        <tr key={`${l.at}|${l.gw}|${i}`} data-testid="gw-orphan-row">
                          <td className="mono" title={l.at}>{fmtTime(at(l.at))}</td>
                          <td className="mono">{l.gw}</td>
                          <td className="mono">{l.account ?? '—'}</td>
                          <WhoCell l={l} names={data?.names} />
                          <td className="mono muted">{l.serial ?? '번호 없음'}</td>
                          <td className="muted">{issuedText(l, data?.state === 'ok')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {data?.state !== 'ok' && !others && orphanOthers > 0 && orphans.length > 0 && (
                <p className="muted access-log__note">기계 · 시험/관리 토큰 접속 {orphanOthers}번은 접어 두었어요.</p>
              )}
            </>
          )}

          <SectionHead
            title="들어간 서버 · 시각"
            sub={
              srv?.state === 'ok'
                ? `서버 접속 기록 · 최근 ${srvDays}일 · ${ago(srv.written_age_seconds)}` +
                  (srv.servers_known ? ` · 읽는 중 ${srv.reading}/${srv.servers.length}곳` : '')
                : '서버 접속 기록'
            }
            asOf={srv?.written_at ? at(srv.written_at) : null}
            onRefresh={() => runAll(setBusy, [load])}
            busy={busy}
            source="gw 가 5분마다 '기록 읽기만 되는 2분짜리 도장' 으로 자기 뒤 서버의 sshd 기록을 받아 금고에 보냄(서버엔 아무것도 안 깖) → IdP 서버가 1분마다 모아 요약 → 수집기가 읽어 올림"
          />
          {srvErr && <div className="card placeholder access-msg">서버 접속 기록을 불러오지 못했어요 — {srvErr}</div>}
          {!srv && !srvErr && <div className="card placeholder access-msg">불러오는 중…</div>}
          {srv?.state === 'off' && (
            <div className="card placeholder access-msg">아직 연결 전이에요 — 수집기가 서버 접속 기록을 올린 적이 없어요.</div>
          )}
          {srv?.state === 'unknown' && (
            <div className="card placeholder access-msg access-msg--warn" role="status" data-testid="server-unknown">
              {srvWhy}. 들어간 서버 칸도 '모름' 으로 두었어요.
            </div>
          )}
          {srv?.state === 'ok' && (
            <>
              <h3 className="access-log__sub">서버 읽기 상태</h3>
              <div className="card access-log__gws">
                <ServerReads srv={srv} />
              </div>
              {srv.unlinked > 0 && (
                <p className="muted access-log__note" data-testid="server-unlinked">
                  목록과 못 이음 —{' '}
                  {srv.servers
                    .filter((x) => x.link === 'unlinked')
                    .map((x) => `${x.server}(${x.gw ?? 'gw 모름'})`)
                    .join(', ')}{' '}
                  (gw 가 환경 · 서비스를 안 보냄 — trust 전이거나 옛 꾸러미)
                </p>
              )}
              {srv.inventory.state !== 'ok' && srv.inventory.reason && <p className="muted access-log__note">{srv.inventory.reason}</p>}
              {srv.notes.length > 0 && <p className="muted access-log__note">{srv.notes.join(' · ')}</p>}

              <h3 className="access-log__sub">
                {data?.state === 'ok'
                  ? '발급 기록과 못 이은 서버 접속 — 번호 기록 설정 전에 받았거나 14일 넘은 인증서'
                  : '들어간 서버 · 시각 — 발급 기록을 못 봐서 이어 붙이지 못했어요'}
              </h3>
              {srv.events.length === 0 ? (
                <div className="card placeholder access-msg" data-testid="server-no-logins">
                  {srv.reading > 0
                    ? `읽는 중인 서버 ${srv.reading}곳에는 최근 ${srvDays}일 들어온 기록이 없어요` +
                      (notReading > 0 ? ` — 안 읽는(못 읽은 · 끊긴 · 목록에만 있는) 서버 ${notReading}곳은 몰라요` : '')
                    : '읽는 중인 서버가 없어 들어간 기록을 볼 수 없어요'}
                </div>
              ) : srvOrphans.length === 0 ? (
                <p className="muted access-log__note">
                  {srvOrphanAll.length === 0
                    ? '없어요 — 모든 서버 접속이 위 발급 기록에 이어 붙었어요.'
                    : `고른 조건에 맞는 것이 없어요(접어 둔 기계 · 시험/관리 토큰 포함 ${srvOrphanAll.length}번).`}
                </p>
              ) : (
                <div className="card">
                  <table className="grid">
                    <thead>
                      <tr>
                        <th>들어간 시각</th>
                        <th>서버</th>
                        <th>gw</th>
                        <th>계정</th>
                        <th>누가</th>
                        <th>인증서 번호</th>
                        <th>발급</th>
                        <th>거친 gw(같은 번호)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {srvOrphans.map((l, i) => (
                        <tr key={`${l.at}|${l.gw}|${l.server}|${i}`} data-testid="server-orphan-row">
                          <td className="mono" title={l.at}>{fmtTime(at(l.at))}</td>
                          <td className="mono" title={l.service ?? ''}>{l.server}</td>
                          <td className="mono">{l.gw ?? '—'}</td>
                          <td className="mono">{l.account ?? '—'}</td>
                          <WhoCell l={l} names={data?.names} />
                          <td className="mono muted">{l.serial ?? '번호 없음'}</td>
                          <td className="muted">{issuedText(l, data?.state === 'ok')}</td>
                          <td>
                            <ViaGw l={l} feed={gwFeed} byserial={byserial} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {data?.state !== 'ok' && !others && srvOrphanOthers > 0 && srvOrphans.length > 0 && (
                <p className="muted access-log__note">기계 · 시험/관리 토큰 서버 접속 {srvOrphanOthers}번은 접어 두었어요.</p>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
