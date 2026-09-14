import { useEffect, useState } from 'react'
import { fetchCicd, type CicdRow } from '../api'

function statusBadge(r: CicdRow) {
  if (!r.has_cicd) return <span className="badge badge--muted">없음</span>
  switch (r.status) {
    case 'success':
      return <span className="badge badge--ok">성공</span>
    case 'failed':
      return <span className="badge badge--danger">실패</span>
    case 'running':
    case 'pending':
      return <span className="badge badge--warn">실행중</span>
    case 'canceled':
    case 'skipped':
      return <span className="badge badge--muted">{r.status}</span>
    default:
      return <span className="badge badge--muted">{r.status ?? '—'}</span>
  }
}

export default function Cicd() {
  const [rows, setRows] = useState<CicdRow[] | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    fetchCicd().then(setRows).catch(() => setErr(true))
  }, [])

  const failed = (rows ?? []).filter((r) => r.status === 'failed').length

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">CI/CD 현황</h1>
        <p className="page-sub">
          서비스별 GitLab 파이프라인 상태{rows ? ` · 실패 ${failed}건` : ''}
        </p>
      </div>

      <div className="card">
        <table className="grid">
          <thead>
            <tr>
              <th>서비스</th>
              <th>repo</th>
              <th>CI/CD</th>
              <th>최근 상태</th>
              <th>브랜치</th>
              <th>최근 실행</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((r) => (
              <tr key={r.service}>
                <td>
                  {r.web_url ? (
                    <a href={r.web_url} target="_blank" rel="noreferrer">{r.service}</a>
                  ) : (
                    r.service
                  )}
                </td>
                <td className="mono">{r.project ?? '—'}</td>
                <td>{r.has_cicd ? <span className="badge badge--ok">있음</span> : <span className="muted">없음</span>}</td>
                <td>{statusBadge(r)}</td>
                <td className="mono">{r.ref ?? '—'}</td>
                <td className="muted">{r.collected_at ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {!rows && !err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>불러오는 중…</div>
        )}
        {rows && rows.length === 0 && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            아직 등록된 서비스가 없습니다 — 대상 추가 후 러너로 수집:{' '}
            <span className="mono">python -m runner.cli cicd</span>
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
