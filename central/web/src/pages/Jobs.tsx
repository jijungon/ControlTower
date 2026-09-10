type Row = { t: string; kind: string; target: string; by: string; result: 'ok' | 'fail' }

const ROWS: Row[] = [
  { t: '2026-09-10 10:32', kind: '수집', target: 'prod 그룹 (12대)', by: 'runner:local', result: 'ok' },
  { t: '2026-09-10 09:15', kind: '배포', target: 'nginx.conf → web (5대)', by: 'joji', result: 'ok' },
  { t: '2026-09-09 18:40', kind: '배포', target: 'app.env → app-02', by: 'joji', result: 'fail' },
]

export default function Jobs() {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">작업 이력</h1>
        <p className="page-sub">수집 · 배포 job 로그 + 감사 로그 (예시 데이터)</p>
      </div>
      <div className="card">
        <table className="grid">
          <thead>
            <tr><th>시각</th><th>종류</th><th>대상</th><th>실행자</th><th>결과</th></tr>
          </thead>
          <tbody>
            {ROWS.map((r, i) => (
              <tr key={i}>
                <td className="mono">{r.t}</td>
                <td>{r.kind}</td>
                <td>{r.target}</td>
                <td className="muted">{r.by}</td>
                <td>
                  {r.result === 'ok'
                    ? <span className="badge badge--ok">성공</span>
                    : <span className="badge badge--danger">실패·롤백</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
