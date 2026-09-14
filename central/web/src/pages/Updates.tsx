import { Fragment, useEffect, useState } from 'react'
import { fetchUpdates, type UpdateRow } from '../api'

export default function Updates() {
  const [rows, setRows] = useState<UpdateRow[] | null>(null)
  const [err, setErr] = useState(false)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    fetchUpdates()
      .then((r) => {
        setRows(r)
        const first = r.find((x) => x.pending > 0)
        if (first) setOpen(first.hostname)
      })
      .catch(() => setErr(true))
  }, [])

  const totalSecurity = (rows ?? []).reduce((a, r) => a + r.security, 0)

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">업데이트</h1>
        <p className="page-sub">
          서버별 대기 중인 OS 패치(apt) · 서버를 누르면 항목 표시
          {rows ? ` · 보안 ${totalSecurity}건` : ''}
        </p>
      </div>

      <div className="card">
        <table className="grid">
          <thead>
            <tr>
              <th>서버</th>
              <th>대기</th>
              <th>보안</th>
              <th>확인</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((r) => {
              const isOpen = open === r.hostname
              return (
                <Fragment key={r.server_id}>
                  <tr className="clickable" onClick={() => setOpen(isOpen ? null : r.hostname)}>
                    <td>
                      <span className="caret">{r.pending > 0 ? (isOpen ? '▾' : '▸') : ''}</span>
                      {r.hostname}
                    </td>
                    <td>{r.error ? <span className="badge badge--danger">수집 실패</span> : r.pending}</td>
                    <td>
                      {r.security > 0 ? (
                        <span className="badge badge--danger">{r.security}</span>
                      ) : (
                        <span className="muted">0</span>
                      )}
                    </td>
                    <td className="muted">{r.collected_at ?? '—'}</td>
                  </tr>
                  {isOpen && (
                    <tr className="detail-row">
                      <td colSpan={4}>
                        {r.error ? (
                          <div className="muted">수집 실패 — {r.error}</div>
                        ) : r.pending === 0 ? (
                          <div className="muted">대기 중인 업데이트 없음</div>
                        ) : (
                          <table className="subgrid">
                            <thead>
                              <tr>
                                <th>패키지</th>
                                <th>현재 → 대상</th>
                                <th>구분</th>
                              </tr>
                            </thead>
                            <tbody>
                              {r.packages.map((p) => (
                                <tr key={p.name}>
                                  <td className="mono">{p.name}</td>
                                  <td className="mono">{p.from} → {p.to}</td>
                                  <td>
                                    {p.security ? (
                                      <span className="badge badge--danger">보안</span>
                                    ) : (
                                      <span className="muted">일반</span>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>

        {!rows && !err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>불러오는 중…</div>
        )}
        {rows && rows.length === 0 && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            아직 수집된 업데이트가 없습니다 — 러너로 수집하세요:{' '}
            <span className="mono">python -m runner.cli updates</span>
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
