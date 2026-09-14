import { useEffect, useState } from 'react'
import { fetchAudit, type AuditRow } from '../api'

const ACTION_LABEL: Record<string, string> = {
  'server.import': '서버 임포트',
  'conn.test': '연결 테스트',
  'conf.collect': '설정 수집',
  'conf.adopt': '기준본 채택',
  'updates.collect': '업데이트 수집',
}

function target(r: AuditRow): string {
  if (r.target_id) return r.target_id
  return r.target_type ?? '—'
}

export default function Jobs() {
  const [rows, setRows] = useState<AuditRow[] | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    fetchAudit().then(setRows).catch(() => setErr(true))
  }, [])

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">작업 이력</h1>
        <p className="page-sub">
          러너·중앙 액션 감사 로그{rows ? ` · ${rows.length}건` : ''}
        </p>
      </div>

      <div className="card">
        <table className="grid">
          <thead>
            <tr>
              <th>시각</th>
              <th>작업</th>
              <th>대상</th>
              <th>실행자</th>
              <th>상세</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((r) => (
              <tr key={r.id}>
                <td className="mono">{r.created_at ?? '—'}</td>
                <td>{ACTION_LABEL[r.action] ?? r.action}</td>
                <td>{target(r)}</td>
                <td className="muted">{r.actor}</td>
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
            아직 기록된 작업이 없습니다 — 러너가 수집·테스트를 실행하면 이력이 쌓입니다.
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
