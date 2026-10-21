import { useEffect, useRef, useState } from 'react'
import { fetchHostStatus, type HostStatus } from '../api'
import { useAuthExpired } from '../authExpiry'

// 화면 맨 위 한 줄 — 서버가 스스로 적는 상태(IdP 서버 status.json). 초록 = 정상 · 빨강 = 경보 · 회색 = 모름
// 서버가 상태를 적고 있어도 보는 사람이 없으면 장애를 오래 모른다 → 모든 탭에서 보이는 자리에 둔다.
// '못 봤다' 를 '정상' 으로 보이지 않게: 경보면 문제와 못 본 것을 둘 다, 불러오지 못하면 초록을 그대로 두지 않고 '모름'.
const NAME: Record<string, string> = { idp: 'IdP 서버' }
const POLL_MS = 30_000

function ago(sec?: number | null): string | null {
  if (sec == null) return null
  if (sec < 60) return '방금'
  const m = Math.floor(sec / 60)
  return m < 120 ? `${m}분 전` : `${Math.floor(m / 60)}시간 전`
}

function Line({ r }: { r: HostStatus }) {
  const name = NAME[r.source] ?? r.source
  const host = r.host ? ` · ${r.host}` : ''
  const when = ago(r.written_age_seconds)
  if (r.state === 'ok')
    return (
      <div className="host-status host-status--ok" role="status">
        ● {name} 정상{host}
        {when && <span className="host-status__meta">{when} 기록</span>}
      </div>
    )
  if (r.state === 'unknown')
    return (
      <div className="host-status host-status--unknown" role="alert">
        <strong>○ {name} 상태 모름{host}</strong>
        {r.reasons.map((x) => (
          <span key={x}>{x}</span>
        ))}
        {when && <span className="host-status__meta">마지막 기록 {when}</span>}
      </div>
    )
  return (
    <div className="host-status host-status--alert" role="alert">
      <strong>⚠ {name} 경보{host}</strong>
      {r.reasons.map((x) => (
        <span key={x}>{x}</span>
      ))}
      {r.problems.length > 0 && <span>문제: {r.problems.join(' · ')}</span>}
      {r.unread.length > 0 && <span>못 본 것: {r.unread.join(' · ')}</span>}
      {when && <span className="host-status__meta">{when} 기록</span>}
    </div>
  )
}

export default function HostStatusBar() {
  const [rows, setRows] = useState<HostStatus[] | null>(null)
  const [err, setErr] = useState(false)
  const had = useRef(false) // 한 번이라도 상태가 있었나 — 있었는데 못 불러오면 '모름'(기능이 꺼진 것과 구분)
  const expired = useAuthExpired()

  useEffect(() => {
    let alive = true
    const load = () =>
      fetchHostStatus()
        .then((d) => {
          if (!alive) return
          setRows(d)
          setErr(false)
          if (d.length) had.current = true
        })
        .catch(() => alive && setErr(true))
    load()
    const t = setInterval(load, POLL_MS)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  if (expired) return null // 로그인 만료 — 맨 위 '로그인이 만료됐어요' 한 줄이 이유를 말함(초록은 그대로 두지 않음)
  if (err && had.current)
    return (
      <div className="host-status host-status--unknown" role="alert">
        <strong>○ 서버 상태 모름</strong>
        <span>ControlTower 에서 불러오지 못함 — 마지막으로 본 상태를 그대로 믿지 마세요</span>
      </div>
    )
  if (!rows || rows.length === 0) return null // 아무도 안 올림 = 이 기능을 안 씀
  return (
    <>
      {rows.map((r) => (
        <Line key={r.source} r={r} />
      ))}
    </>
  )
}
