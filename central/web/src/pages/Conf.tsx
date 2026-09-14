import { useEffect, useState } from 'react'
import { fetchConf, type ConfRow, type ConfStatus } from '../api'

const BADGE: Record<ConfStatus, JSX.Element> = {
  synced: <span className="badge badge--ok">동기화됨</span>,
  drift: <span className="badge badge--warn">드리프트</span>,
  no_baseline: <span className="badge badge--muted">기준본 없음</span>,
  error: <span className="badge badge--danger">수집 실패</span>,
}

export default function Conf() {
  const [rows, setRows] = useState<ConfRow[] | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    fetchConf().then(setRows).catch(() => setErr(true))
  }, [])

  const drift = (rows ?? []).filter((r) => r.status === 'drift').length

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">설정 (conf)</h1>
        <p className="page-sub">
          서버별 기준본 ↔ 실제본 비교{rows ? ` · 드리프트 ${drift}건` : ''}
        </p>
      </div>

      <div className="card">
        <table className="grid">
          <thead>
            <tr>
              <th>서버</th>
              <th>기준본 파일</th>
              <th>상태</th>
              <th>비고</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((r) => (
              <tr key={`${r.server_id}:${r.path}`}>
                <td>{r.hostname}</td>
                <td className="mono">{r.path}</td>
                <td>{BADGE[r.status]}</td>
                <td className="muted">{r.detail ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {!rows && !err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>불러오는 중…</div>
        )}
        {rows && rows.length === 0 && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            아직 수집된 conf 가 없습니다 — 관리 경로 추가 후{' '}
            <span className="mono">python -m runner.cli conf</span>
          </div>
        )}
        {err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            API 연결 실패 — <span className="mono">make dev</span> 로 중앙 API를 띄우세요.
          </div>
        )}
      </div>
    </div>
  )
}
