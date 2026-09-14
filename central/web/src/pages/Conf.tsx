import { useEffect, useState } from 'react'
import {
  approveApply,
  cancelApply,
  fetchApplyIntents,
  fetchConf,
  planApply,
  type ApplyIntent,
  type ApplyStatus,
  type ConfRow,
  type ConfStatus,
} from '../api'

const BADGE: Record<ConfStatus, JSX.Element> = {
  synced: <span className="badge badge--ok">동기화됨</span>,
  drift: <span className="badge badge--warn">드리프트</span>,
  no_baseline: <span className="badge badge--muted">기준본 없음</span>,
  error: <span className="badge badge--danger">수집 실패</span>,
}

const APPLY_BADGE: Record<ApplyStatus, JSX.Element> = {
  pending: <span className="badge badge--warn">대기</span>,
  approved: <span className="badge badge--ok">승인됨</span>,
  applied: <span className="badge badge--ok">적용됨</span>,
  failed: <span className="badge badge--danger">실패</span>,
  canceled: <span className="badge badge--muted">취소</span>,
}

export default function Conf() {
  const [rows, setRows] = useState<ConfRow[] | null>(null)
  const [err, setErr] = useState(false)
  const [intents, setIntents] = useState<ApplyIntent[]>([])
  const [openDiff, setOpenDiff] = useState<number | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  const loadConf = () => fetchConf().then(setRows).catch(() => setErr(true))
  const loadIntents = () => fetchApplyIntents().then(setIntents).catch(() => setIntents([]))

  useEffect(() => {
    loadConf()
    loadIntents()
  }, [])

  const drift = (rows ?? []).filter((r) => r.status === 'drift').length
  // 이미 대기/승인 중인 (server,path) 는 중복 계획 방지
  const activeKey = new Set(
    intents.filter((i) => i.status === 'pending' || i.status === 'approved').map((i) => `${i.server_id}:${i.path}`),
  )

  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key)
    setMsg(null)
    try {
      await fn()
      await loadIntents()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '요청 실패')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">설정 (conf)</h1>
        <p className="page-sub">서버별 기준본 ↔ 실제본 비교{rows ? ` · 드리프트 ${drift}건` : ''}</p>
      </div>

      {msg && (
        <div className="card" style={{ padding: '10px 14px', marginBottom: 12, color: 'var(--danger, #b3261e)' }}>
          {msg}
        </div>
      )}

      <div className="card">
        <table className="grid">
          <thead>
            <tr>
              <th>서버</th>
              <th>기준본 파일</th>
              <th>상태</th>
              <th>비고</th>
              <th>적용</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((r) => {
              const key = `${r.server_id}:${r.path}`
              return (
                <tr key={key}>
                  <td>{r.hostname}</td>
                  <td className="mono">{r.path}</td>
                  <td>{BADGE[r.status]}</td>
                  <td className="muted">{r.detail ?? ''}</td>
                  <td>
                    {r.status === 'drift' && !activeKey.has(key) ? (
                      <button
                        className="btn btn--sm"
                        disabled={busy === `plan:${key}`}
                        onClick={() => run(`plan:${key}`, () => planApply(r.server_id, r.path))}
                      >
                        적용 계획
                      </button>
                    ) : r.status === 'drift' ? (
                      <span className="muted">계획됨</span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {!rows && !err && <div className="placeholder" style={{ padding: '28px 16px' }}>불러오는 중…</div>}
        {rows && rows.length === 0 && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            아직 수집된 conf 가 없습니다 — 관리 경로 추가 후 <span className="mono">python -m runner.cli conf</span>
          </div>
        )}
        {err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            API 연결 실패 — <span className="mono">make dev</span> 로 중앙 API를 띄우세요.
          </div>
        )}
      </div>

      {intents.length > 0 && (
        <>
          <div className="subhead">적용 대기 · 이력</div>
          <div className="card">
            <table className="grid">
              <thead>
                <tr>
                  <th>서버</th>
                  <th>파일</th>
                  <th>상태</th>
                  <th>diff</th>
                  <th>작업</th>
                </tr>
              </thead>
              <tbody>
                {intents.map((it) => (
                  <tr key={it.id}>
                    <td>{it.hostname}</td>
                    <td className="mono">{it.path}</td>
                    <td>{APPLY_BADGE[it.status]}</td>
                    <td>
                      <button className="btn btn--sm" onClick={() => setOpenDiff(openDiff === it.id ? null : it.id)}>
                        {openDiff === it.id ? '숨기기' : '보기'}
                      </button>
                    </td>
                    <td>
                      {it.status === 'pending' && (
                        <button
                          className="btn btn--sm btn--primary"
                          disabled={busy === `approve:${it.id}`}
                          onClick={() => run(`approve:${it.id}`, () => approveApply(it.id))}
                        >
                          승인
                        </button>
                      )}
                      {(it.status === 'pending' || it.status === 'approved') && (
                        <button
                          className="btn btn--sm"
                          disabled={busy === `cancel:${it.id}`}
                          onClick={() => run(`cancel:${it.id}`, () => cancelApply(it.id))}
                        >
                          취소
                        </button>
                      )}
                      {it.status === 'approved' && <span className="muted"> · 러너 적용 대기</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {openDiff !== null && (
              <pre className="diff" style={{ margin: 0, padding: '12px 16px', overflowX: 'auto', fontSize: 13 }}>
                {intents.find((i) => i.id === openDiff)?.diff || '(diff 없음)'}
              </pre>
            )}
          </div>
        </>
      )}
    </div>
  )
}
