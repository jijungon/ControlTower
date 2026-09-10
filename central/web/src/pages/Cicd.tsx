type Status = 'ok' | 'warn' | 'danger'
type Row = { svc: string; repo: string; deploy: string; exec: 'docker' | 'shell'; status: Status }

// supercycl 조사 기반 예시
const ROWS: Row[] = [
  { svc: 'admin', repo: 'aggregator-admin', deploy: 'push_src', exec: 'docker', status: 'ok' },
  { svc: 'chat', repo: 'chat-service', deploy: 'push_src', exec: 'docker', status: 'ok' },
  { svc: 'aggregator', repo: 'aggregator_web', deploy: 'dev·stg 직배포', exec: 'shell', status: 'danger' },
  { svc: 'brandsite', repo: 'brandsite_web', deploy: 'dev·stg 직배포', exec: 'shell', status: 'warn' },
  { svc: 'youthmeta-mobile', repo: 'youthmeta_mobile', deploy: 'dev·prod 직배포', exec: 'shell', status: 'danger' },
]

const BADGE: Record<Status, JSX.Element> = {
  ok: <span className="badge badge--ok">정상</span>,
  warn: <span className="badge badge--warn">부분</span>,
  danger: <span className="badge badge--danger">이관 대상</span>,
}

export default function Cicd() {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">CI/CD 배포 현황</h1>
        <p className="page-sub">서비스별 배포 경로 · executor · 이관 상태 (repo → center, 예시 데이터)</p>
      </div>
      <div className="card">
        <table className="grid">
          <thead>
            <tr><th>서비스</th><th>repo</th><th>배포</th><th>executor</th><th>상태</th></tr>
          </thead>
          <tbody>
            {ROWS.map((r) => (
              <tr key={r.svc}>
                <td>{r.svc}</td>
                <td className="mono">{r.repo}</td>
                <td>{r.deploy}</td>
                <td><span className="badge badge--muted">{r.exec}</span></td>
                <td>{BADGE[r.status]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
