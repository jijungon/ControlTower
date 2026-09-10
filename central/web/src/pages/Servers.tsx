import { useEffect, useState } from 'react'
import { fetchServers, type Server } from '../api'

export default function Servers() {
  const [q, setQ] = useState('')
  const [servers, setServers] = useState<Server[] | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    fetchServers().then(setServers).catch(() => setErr(true))
  }, [])

  const rows = (servers ?? []).filter((s) =>
    `${s.hostname} ${s.ip ?? ''} ${s.ssh_user}`.toLowerCase().includes(q.toLowerCase()),
  )

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">서버 · 접속키 인벤토리</h1>
        <p className="page-sub">
          ~/.ssh/config 기준 · 서버가 무슨 키로 접속되나{servers ? ` · ${servers.length}대` : ''}
        </p>
      </div>

      <div className="toolbar">
        <input
          className="search"
          placeholder="서버 · IP · user 검색"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
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
            {rows.map((s) => (
              <tr key={s.id}>
                <td><span className={`dot dot--${s.status}`} title={s.status} />{s.hostname}</td>
                <td className="mono">{s.ip ?? '—'}</td>
                <td>{s.ssh_user}</td>
                <td>
                  {s.access_control ? <span className="tag">{s.access_control}</span> : <span className="muted">—</span>}
                </td>
                <td>
                  {s.credential_alias ? <span className="mono">{s.credential_alias}</span> : <span className="muted">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {!servers && !err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>불러오는 중…</div>
        )}
        {servers && servers.length === 0 && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            아직 임포트된 서버가 없습니다 — 러너로 임포트하세요:{' '}
            <span className="mono">python -m runner.cli import</span>
          </div>
        )}
        {err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            API에 연결하지 못했습니다 — <span className="mono">make dev</span> 로 중앙 API를 띄우세요.
          </div>
        )}
      </div>
    </div>
  )
}
