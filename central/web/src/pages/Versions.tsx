import { useEffect, useState } from 'react'
import { addRepoTarget, fetchRepoTargets, fetchVersions, type RepoTarget, type VersionRow } from '../api'

// 컬럼 선호 순서(존재하는 툴만 노출). 그 외 툴은 뒤에 알파벳순으로.
const PREFERRED = ['node', 'npm', 'nest', 'java', 'python', 'docker']

function columns(rows: VersionRow[]): string[] {
  const seen = new Set<string>()
  rows.forEach((r) => Object.keys(r.tools).forEach((t) => seen.add(t)))
  const extra = [...seen].filter((t) => !PREFERRED.includes(t)).sort()
  return [...PREFERRED.filter((t) => seen.has(t)), ...extra]
}

function kindTag(kind: VersionRow['kind']) {
  return kind === 'server' ? (
    <span className="badge badge--muted">빌드</span>
  ) : (
    <span className="badge badge--muted">repo</span>
  )
}

export default function Versions() {
  const [rows, setRows] = useState<VersionRow[] | null>(null)
  const [err, setErr] = useState(false)
  const [targets, setTargets] = useState<RepoTarget[]>([])
  const [repo, setRepo] = useState('')
  const [proj, setProj] = useState('')
  const [msg, setMsg] = useState<string | null>(null)

  const loadTargets = () => fetchRepoTargets().then(setTargets).catch(() => setTargets([]))

  useEffect(() => {
    fetchVersions().then(setRows).catch(() => setErr(true))
    loadTargets()
  }, [])

  async function addTarget() {
    if (!repo.trim() || !proj.trim()) return
    setMsg(null)
    try {
      await addRepoTarget(repo.trim(), proj.trim())
      setRepo('')
      setProj('')
      await loadTargets()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '추가 실패')
    }
  }

  const cols = columns(rows ?? [])

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">버전 · 빌드</h1>
        <p className="page-sub">
          버전 매트릭스 · 빌드 서버 툴체인 + GitLab repo 선언본{rows ? ` · ${rows.length}건` : ''}
        </p>
      </div>

      <div className="card">
        <table className="grid">
          <thead>
            <tr>
              <th>대상</th>
              <th>구분</th>
              {cols.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((r) => (
              <tr key={`${r.kind}:${r.name}`}>
                <td>{r.name}</td>
                <td>{kindTag(r.kind)}</td>
                {cols.map((c) => (
                  <td key={c}>
                    {r.tools[c] ? (
                      <span className="mono">{r.tools[c]}</span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>

        {!rows && !err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>불러오는 중…</div>
        )}
        {rows && rows.length === 0 && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            아직 수집된 버전이 없습니다 — 러너로 수집하세요:{' '}
            <span className="mono">python -m runner.cli versions</span> ·{' '}
            <span className="mono">versions-repo</span>
          </div>
        )}
        {err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            API 연결 실패 — <span className="mono">make dev</span> 로 중앙 API를 띄우세요.
          </div>
        )}
      </div>

      <div className="subhead">GitLab 선언본 대상</div>
      <div className="toolbar" style={{ flexWrap: 'wrap' }}>
        <input className="search" style={{ minWidth: 160 }} placeholder="표시 이름 (repo)" value={repo} onChange={(e) => setRepo(e.target.value)} />
        <input className="search" style={{ minWidth: 220 }} placeholder="GitLab 프로젝트 (group/repo 또는 id)" value={proj} onChange={(e) => setProj(e.target.value)} />
        <button className="btn" onClick={addTarget}>대상 추가</button>
      </div>
      {msg && <div className="card" style={{ padding: '10px 14px', marginBottom: 12, color: 'var(--danger,#b3261e)' }}>{msg}</div>}
      <div className="card">
        <table className="grid">
          <thead>
            <tr><th>repo</th><th>GitLab 프로젝트</th></tr>
          </thead>
          <tbody>
            {targets.map((t) => (
              <tr key={t.repo}>
                <td>{t.repo}</td>
                <td className="mono">{t.project}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {targets.length === 0 && (
          <div className="placeholder" style={{ padding: '20px 16px' }}>
            등록된 대상이 없습니다 — 추가 후 <span className="mono">python -m runner.cli versions-repo</span> (GitLab 설정 시)
          </div>
        )}
      </div>
    </div>
  )
}
