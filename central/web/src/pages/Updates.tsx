type Row = { server: string; pending: number; security: number; checked: string }

const ROWS: Row[] = [
  { server: 'web-01', pending: 8, security: 3, checked: '10분 전' },
  { server: 'db-01', pending: 2, security: 2, checked: '10분 전' },
  { server: 'build-01', pending: 0, security: 0, checked: '10분 전' },
]

export default function Updates() {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">업데이트</h1>
        <p className="page-sub">서버별 대기 중인 OS 패치(apt) · 보안 구분 (예시 데이터)</p>
      </div>
      <div className="card">
        <table className="grid">
          <thead>
            <tr><th>서버</th><th>대기</th><th>보안</th><th>확인</th></tr>
          </thead>
          <tbody>
            {ROWS.map((r) => (
              <tr key={r.server}>
                <td>{r.server}</td>
                <td>{r.pending}</td>
                <td>{r.security > 0 ? <span className="badge badge--danger">{r.security}</span> : <span className="muted">0</span>}</td>
                <td className="muted">{r.checked}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
