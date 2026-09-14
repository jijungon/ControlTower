import { useEffect, useState } from 'react'
import { fetchConf, fetchServers, fetchUpdates, type ConfRow, type Server, type UpdateRow } from '../api'

function latest(times: (string | null | undefined)[]): string {
  const t = times.filter((x): x is string => !!x).sort()
  return t.length ? t[t.length - 1] : '—'
}

export default function Dashboard() {
  const [servers, setServers] = useState<Server[] | null>(null)
  const [conf, setConf] = useState<ConfRow[] | null>(null)
  const [updates, setUpdates] = useState<UpdateRow[] | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    Promise.all([fetchServers(), fetchConf(), fetchUpdates()])
      .then(([s, c, u]) => {
        setServers(s)
        setConf(c)
        setUpdates(u)
      })
      .catch(() => setErr(true))
  }, [])

  const online = (servers ?? []).filter((s) => s.status === 'online').length
  const total = (servers ?? []).length
  const drift = (conf ?? []).filter((r) => r.status === 'drift').length
  const pending = (updates ?? []).reduce((a, r) => a + r.pending, 0)
  const security = (updates ?? []).reduce((a, r) => a + r.security, 0)

  const ready = servers !== null && conf !== null && updates !== null

  const stats = [
    { num: total ? `${online}/${total}` : '—', label: '온라인 서버', tone: total && online === total ? 'ok' : 'warn' },
    { num: String(drift), label: '드리프트', tone: drift > 0 ? 'warn' : 'ok' },
    { num: String(pending), label: '대기 업데이트', tone: pending > 0 ? 'warn' : 'ok' },
    { num: String(security), label: '보안 패치', tone: security > 0 ? 'danger' : 'ok' },
  ]

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">대시보드</h1>
        <p className="page-sub">서버·설정·업데이트 실시간 집계</p>
      </div>

      {err && (
        <div className="card">
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            API 연결 실패 — <span className="mono">make dev</span> 로 중앙 API를 띄우세요.
          </div>
        </div>
      )}

      {!err && (
        <>
          <div className="stats">
            {stats.map((s) => (
              <div key={s.label} className={`stat stat--${s.tone}`}>
                <div className="num">{ready ? s.num : '…'}</div>
                <div className="label">{s.label}</div>
              </div>
            ))}
          </div>

          <div className="subhead">수집 현황</div>
          <div className="card">
            <table className="grid">
              <thead>
                <tr>
                  <th>도메인</th>
                  <th>수집</th>
                  <th>이슈</th>
                  <th>최근 수집</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>서버 · 접속키</td>
                  <td>{total}대</td>
                  <td>
                    {total - online > 0 ? (
                      <span className="badge badge--warn">오프라인/미확인 {total - online}</span>
                    ) : (
                      <span className="badge badge--ok">전원 온라인</span>
                    )}
                  </td>
                  <td className="muted">{latest((servers ?? []).map((s) => s.last_checked_at))}</td>
                </tr>
                <tr>
                  <td>설정 (conf)</td>
                  <td>{conf?.length ?? 0}건</td>
                  <td>
                    {drift > 0 ? (
                      <span className="badge badge--warn">드리프트 {drift}</span>
                    ) : (
                      <span className="badge badge--ok">동기화</span>
                    )}
                  </td>
                  <td className="muted">{latest((conf ?? []).map((r) => r.collected_at))}</td>
                </tr>
                <tr>
                  <td>업데이트</td>
                  <td>{updates?.length ?? 0}대</td>
                  <td>
                    {security > 0 ? (
                      <span className="badge badge--danger">보안 {security}</span>
                    ) : pending > 0 ? (
                      <span className="badge badge--warn">대기 {pending}</span>
                    ) : (
                      <span className="badge badge--ok">최신</span>
                    )}
                  </td>
                  <td className="muted">{latest((updates ?? []).map((r) => r.collected_at))}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
