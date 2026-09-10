import { useEffect, useState } from 'react'
import { fetchServers } from '../api'

type Row = {
  server: string
  ip: string
  user: string
  access: string | null // vpn/접근제어: dbsafe·ncloud 등
  keyFile: string
  fp: string
}

// 예시 데이터 (실데이터는 Phase 0 의 ~/.ssh/config 임포트로 채워짐)
const MOCK: Row[] = [
  { server: 'web-01', ip: '10.89.2.67', user: 'deploy', access: 'ncloud', keyFile: 'gw_prod_ed25519', fp: 'SHA256:aB3d…9f' },
  { server: 'db-01', ip: '10.89.3.10', user: 'dbadmin', access: 'dbsafe', keyFile: 'db_ed25519', fp: 'SHA256:c7X1…e2' },
  { server: 'build-01', ip: '144.24.73.187', user: 'ci', access: null, keyFile: 'build_ed25519', fp: 'SHA256:0kP9…4a' },
]

export default function Servers() {
  const [q, setQ] = useState('')
  const [apiCount, setApiCount] = useState<number | null>(null)

  useEffect(() => {
    fetchServers()
      .then((s) => setApiCount(s.length))
      .catch(() => setApiCount(null))
  }, [])

  const rows = MOCK.filter((r) =>
    `${r.server} ${r.ip} ${r.user}`.toLowerCase().includes(q.toLowerCase()),
  )

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">서버 · 접속키 인벤토리</h1>
        <p className="page-sub">
          ~/.ssh/config 기준 · 서버가 무슨 키로 접속되나
          {apiCount !== null ? ` · API 등록 ${apiCount}대` : ' · (예시 데이터)'}
        </p>
      </div>

      <div className="toolbar">
        <input
          className="search"
          placeholder="서버 · IP · user 검색"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="pill">서버 추가</button>
      </div>

      <div className="card">
        <table className="grid">
          <thead>
            <tr>
              <th>서버</th>
              <th>IP</th>
              <th>user</th>
              <th>vpn/접근제어</th>
              <th>키</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.server}>
                <td>{r.server}</td>
                <td className="mono">{r.ip}</td>
                <td>{r.user}</td>
                <td>{r.access ? <span className="tag">{r.access}</span> : <span className="muted">—</span>}</td>
                <td>
                  <span className="mono">{r.keyFile}</span> <span className="fp">{r.fp}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
