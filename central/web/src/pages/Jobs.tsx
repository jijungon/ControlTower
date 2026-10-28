import { useEffect, useState } from 'react'
import { fetchAuditPage, type AuditRow } from '../api'
import Pager, { usePageSize } from '../components/Pager'
import SectionHead, { fmtTime, runAll } from '../components/SectionHead'

const ACTION_LABEL: Record<string, string> = {
  'server.import': '서버 임포트',
  'conn.test': '연결 테스트',
  'conf.collect': '설정 수집',
  'conf.adopt': '기준본 채택',
  'conf.apply_plan': '적용 계획',
  'conf.apply_approve': '적용 승인',
  'conf.apply_cancel': '적용 취소',
  'conf.apply_result': '적용 결과',
  'conf.apply_rollback': '적용 되돌림',
  'updates.collect': '업데이트 수집',
  'versions.collect': '버전 수집',
  'versions.repo_collect': '선언본 수집',
  'cicd.collect': 'CI/CD 수집',
  'cicd.shape': '비교표 수집',
  'cicd.config': 'config 수집',
  'inventory.edit': '목록 고침(금고)',
  'inventory.edit_unknown': '목록 고침 — 저장됐는지 모름',
}

function target(r: AuditRow): string {
  if (r.target_id) return r.target_id
  return r.target_type ?? '—'
}

export default function Jobs() {
  const [rows, setRows] = useState<AuditRow[] | null>(null)
  const [total, setTotal] = useState(0)
  const [latest, setLatest] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [size, setSize] = usePageSize('jobs')
  const [err, setErr] = useState(false)
  const [busy, setBusy] = useState(false)

  // 계속 쌓이니까 한 페이지씩만 받아 옴(최신순)
  const load = () =>
    fetchAuditPage(size, page * size)
      .then(({ rows: r, total: t }) => {
        setRows(r)
        setTotal(t)
        if (page === 0) setLatest(r[0]?.created_at ?? null)
        setErr(false)
      })
      .catch(() => setErr(true))

  useEffect(() => {
    load()
  }, [page, size])

  return (
    <div>
      <SectionHead
        title="작업이력 (전체)"
        sub={`ControlTower 가 한 모든 일${rows ? ` · ${total}건` : ''}`}
        asOf={latest}
        onRefresh={() => runAll(setBusy, [load])}
        busy={busy}
        source="중앙 API 가 러너·화면 동작을 그때그때 기록"
      />

      <div className="card">
        <table className="grid">
          <thead>
            <tr>
              <th>시각</th>
              <th>작업</th>
              <th>대상</th>
              <th>실행자</th>
              <th>상세</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((r) => (
              <tr key={r.id}>
                <td className="mono" title={r.created_at ?? ''}>{r.created_at ? fmtTime(r.created_at) : '—'}</td>
                <td>{ACTION_LABEL[r.action] ?? r.action}</td>
                <td>{target(r)}</td>
                <td className="muted">{r.actor}</td>
                <td className="muted">{r.detail ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <Pager label="작업이력" page={page} size={size} total={total} onPage={setPage} onSize={setSize} />

        {!rows && !err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>불러오는 중…</div>
        )}
        {rows && rows.length === 0 && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            아직 기록된 작업이 없습니다 — 러너가 수집·테스트를 실행하면 이력이 쌓입니다.
          </div>
        )}
        {err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            API 연결 실패 — <span className="mono">make dev</span> 로 중앙 API를 띄우세요.
          </div>
        )}
      </div>
    </div>
  )
}
