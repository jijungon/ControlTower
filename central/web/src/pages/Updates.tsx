import { Fragment, useState } from 'react'

type Pkg = { name: string; from: string; to: string; security: boolean }
type Row = { server: string; checked: string; packages: Pkg[] }

// 예시 데이터 (실데이터는 수집기 붙은 뒤)
const ROWS: Row[] = [
  {
    server: 'web-01',
    checked: '10분 전',
    packages: [
      { name: 'openssl', from: '3.0.2', to: '3.0.13', security: true },
      { name: 'libssl3', from: '3.0.2', to: '3.0.13', security: true },
      { name: 'nginx', from: '1.18.0', to: '1.24.0', security: true },
      { name: 'curl', from: '7.81.0', to: '7.88.1', security: false },
      { name: 'libc6', from: '2.35', to: '2.35-0ubuntu3.8', security: false },
      { name: 'tar', from: '1.34', to: '1.34+dfsg-1.2', security: false },
      { name: 'vim', from: '8.2.3995', to: '8.2.5172', security: false },
      { name: 'tzdata', from: '2023c', to: '2024a', security: false },
    ],
  },
  {
    server: 'db-01',
    checked: '10분 전',
    packages: [
      { name: 'openssl', from: '3.0.2', to: '3.0.13', security: true },
      { name: 'sudo', from: '1.9.9', to: '1.9.15', security: true },
    ],
  },
  { server: 'build-01', checked: '10분 전', packages: [] },
]

export default function Updates() {
  const [open, setOpen] = useState<string | null>('web-01')

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">업데이트</h1>
        <p className="page-sub">서버별 대기 중인 OS 패치(apt) · 서버를 누르면 항목 표시 (예시 데이터)</p>
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
            {ROWS.map((r) => {
              const pending = r.packages.length
              const security = r.packages.filter((p) => p.security).length
              const isOpen = open === r.server
              return (
                <Fragment key={r.server}>
                  <tr className="clickable" onClick={() => setOpen(isOpen ? null : r.server)}>
                    <td>
                      <span className="caret">{pending > 0 ? (isOpen ? '▾' : '▸') : ''}</span>
                      {r.server}
                    </td>
                    <td>{pending}</td>
                    <td>{security > 0 ? <span className="badge badge--danger">{security}</span> : <span className="muted">0</span>}</td>
                    <td className="muted">{r.checked}</td>
                  </tr>
                  {isOpen && (
                    <tr className="detail-row">
                      <td colSpan={4}>
                        {pending === 0 ? (
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
                                  <td>{p.security ? <span className="badge badge--danger">보안</span> : <span className="muted">일반</span>}</td>
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
      </div>
    </div>
  )
}
