type Row = { name: string; node?: string; nest?: string; java?: string; docker?: string }

const ROWS: Row[] = [
  { name: 'repo · aggregator_web', node: '20.11', nest: '10.3' },
  { name: 'repo · chat-service', node: '20.11', nest: '10.3' },
  { name: 'repo · pnl_was', java: '17' },
  { name: 'build-01 (빌드 서버)', node: '18.19', java: '17', docker: '24.0' },
]

// 예: node 18 은 EOL 표시
function cell(v?: string) {
  if (!v) return <span className="ver ver--none">—</span>
  const eol = v.startsWith('18')
  return <span className={'ver' + (eol ? ' ver--eol' : '')}>{v}{eol ? ' ⚠' : ''}</span>
}

export default function Versions() {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">버전 · 빌드</h1>
        <p className="page-sub">대상 × 버전 매트릭스 · GitLab 선언본 + 빌드 서버 · ⚠ = EOL (예시 데이터)</p>
      </div>
      <div className="card">
        <table className="grid">
          <thead>
            <tr><th>대상</th><th>node</th><th>nest</th><th>java</th><th>docker</th></tr>
          </thead>
          <tbody>
            {ROWS.map((r) => (
              <tr key={r.name}>
                <td>{r.name}</td>
                <td>{cell(r.node)}</td>
                <td>{cell(r.nest)}</td>
                <td>{cell(r.java)}</td>
                <td>{cell(r.docker)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
