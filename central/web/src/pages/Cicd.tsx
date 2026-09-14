import { useEffect, useState } from 'react'
import { addCicdTarget, fetchCicd, type CicdRow } from '../api'

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
  const [svc, setSvc] = useState('')
  const [proj, setProj] = useState('')
  const [msg, setMsg] = useState<string | null>(null)

  const load = () => fetchCicd().then(setRows).catch(() => setErr(true))

  useEffect(() => {
    load()
  }, [])

  async function add() {
    if (!svc.trim() || !proj.trim()) return
    setMsg(null)
    try {
      await addCicdTarget(svc.trim(), proj.trim())
      setSvc('')
      setProj('')
      await load()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '추가 실패')
    }
  }

  const failed = (rows ?? []).filter((r) => r.status === 'failed').length

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">CI/CD 현황</h1>
        <p className="page-sub">
          서비스별 GitLab 파이프라인 상태{rows ? ` · 실패 ${failed}건` : ''}
        </p>
      </div>

      <div className="toolbar" style={{ flexWrap: 'wrap' }}>
        <input className="search" style={{ minWidth: 160 }} placeholder="서비스 이름" value={svc} onChange={(e) => setSvc(e.target.value)} />
        <input className="search" style={{ minWidth: 220 }} placeholder="GitLab 프로젝트 (group/repo 또는 id)" value={proj} onChange={(e) => setProj(e.target.value)} />
        <button className="btn" onClick={add}>서비스 추가</button>
      </div>
      {msg && <div className="card" style={{ padding: '10px 14px', marginBottom: 12, color: 'var(--danger,#b3261e)' }}>{msg}</div>}

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
