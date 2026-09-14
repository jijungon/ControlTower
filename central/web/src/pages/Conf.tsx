type Status = 'synced' | 'drift' | 'unknown'
type Row = { server: string; file: string; status: Status; detail?: string }

// 서버별로 어떤 파일이 다른지 한눈에 (예시 데이터)
const ROWS: Row[] = [
  { server: 'web-01', file: 'nginx.conf', status: 'drift', detail: 'gzip 설정 누락' },
  { server: 'web-02', file: 'nginx.conf', status: 'synced' },
  { server: 'web-03', file: 'nginx.conf', status: 'synced' },
  { server: 'web-04', file: 'nginx.conf', status: 'synced' },
  { server: 'web-05', file: 'nginx.conf', status: 'drift', detail: 'worker_processes 값 차이' },
  { server: 'app-01', file: 'docker-compose.yml', status: 'synced' },
  { server: 'app-01', file: 'systemd/app.service', status: 'unknown', detail: '미수집' },
  { server: 'app-02', file: 'docker-compose.yml', status: 'drift', detail: '환경변수 차이' },
  { server: 'app-02', file: 'systemd/app.service', status: 'synced' },
  { server: 'app-03', file: 'docker-compose.yml', status: 'synced' },
]

const BADGE: Record<Status, JSX.Element> = {
  synced: <span className="badge badge--ok">동기화됨</span>,
  drift: <span className="badge badge--warn">드리프트</span>,
  unknown: <span className="badge badge--muted">미수집</span>,
}

export default function Conf() {
  const drift = ROWS.filter((r) => r.status === 'drift').length

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">설정 (conf)</h1>
        <p className="page-sub">
          서버별 기준본 ↔ 실제본 비교 · 드리프트 {drift}건 (예시 데이터)
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
            {ROWS.map((r) => (
              <tr key={`${r.server}:${r.file}`}>
                <td>{r.server}</td>
                <td className="mono">{r.file}</td>
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
