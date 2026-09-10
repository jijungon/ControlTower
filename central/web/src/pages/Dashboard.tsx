const STATS = [
  { num: '23/24', label: '온라인 서버', tone: 'ok' },
  { num: '3', label: '드리프트', tone: 'warn' },
  { num: '11', label: '대기 업데이트', tone: 'warn' },
  { num: '2', label: 'EOL 경고', tone: 'danger' },
] as const

const RECENT = [
  { t: '10:32', kind: '수집', target: 'prod 그룹 (12대)' },
  { t: '09:15', kind: '배포', target: 'nginx.conf → web (5대)' },
  { t: '어제', kind: '수집', target: 'GitLab 빌드 버전' },
]

export default function Dashboard() {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">대시보드</h1>
        <p className="page-sub">전체 현황 요약 · 카드를 눌러 상세로 (예시 데이터)</p>
      </div>

      <div className="stats">
        {STATS.map((s) => (
          <div key={s.label} className={`stat stat--${s.tone}`}>
            <div className="num">{s.num}</div>
            <div className="label">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="subhead">최근 작업</div>
      <div className="card">
        <table className="grid">
          <thead>
            <tr><th>시각</th><th>종류</th><th>대상</th><th>결과</th></tr>
          </thead>
          <tbody>
            {RECENT.map((r, i) => (
              <tr key={i}>
                <td className="muted">{r.t}</td>
                <td>{r.kind}</td>
                <td>{r.target}</td>
                <td><span className="badge badge--ok">성공</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
