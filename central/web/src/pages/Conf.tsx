type Status = 'synced' | 'drift' | 'unknown'
type Row = { file: string; targets: string; status: Status; detail?: string }

const ROWS: Row[] = [
  { file: 'nginx.conf', targets: 'web (5대)', status: 'drift', detail: '1대 gzip 설정 누락' },
  { file: 'docker-compose.yml', targets: 'app (3대)', status: 'synced' },
  { file: 'systemd/app.service', targets: 'app (3대)', status: 'unknown', detail: '미수집' },
]

const BADGE: Record<Status, JSX.Element> = {
  synced: <span className="badge badge--ok">동기화됨</span>,
  drift: <span className="badge badge--warn">드리프트</span>,
  unknown: <span className="badge badge--muted">미수집</span>,
}

export default function Conf() {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">설정 (conf)</h1>
        <p className="page-sub">중앙 기준본 ↔ 서버 실제본 · 드리프트 감지 (예시 데이터)</p>
      </div>
      <div className="card">
        <table className="grid">
          <thead>
            <tr><th>기준본 파일</th><th>대상</th><th>상태</th><th>비고</th></tr>
          </thead>
          <tbody>
            {ROWS.map((r) => (
              <tr key={r.file}>
                <td className="mono">{r.file}</td>
                <td>{r.targets}</td>
                <td>{BADGE[r.status]}</td>
                <td className="muted">{r.detail ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
