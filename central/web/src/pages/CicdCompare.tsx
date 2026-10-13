import { useEffect, useState } from 'react'
import { fetchShapes, type DeployCell, type ExecutorCell, type ShapeRow } from '../api'

// 환경 칸 순서(데이터에 있는 환경만 보인다)
const ENV_ORDER = ['dev', 'lab', 'stg', 'preview', 'prod']
const PATH_LABEL: Record<DeployCell['path'], string> = { direct: '직배포', image: '이미지', build: '빌드만' }

// "3.10.12" → [3,10,12], "v18" → [18], "0.1.3-java17" → [0,1,3]. 숫자가 없으면 [].
export function verParts(v?: string | null): number[] {
  const m = (v ?? '').match(/\d+(?:\.\d+)*/)
  return m ? m[0].split('.').map(Number) : []
}

export function cmpVer(a: number[], b: number[]): number {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0)
    if (d !== 0) return Math.sign(d)
  }
  return 0
}

// 같은 종류(key) 안에서 가장 높은 버전. 버전 숫자가 없는 값은 비교에서 뺀다.
export function newestBy(rows: ShapeRow[], pick: (r: ShapeRow) => [string, string] | null): Map<string, string> {
  const best = new Map<string, string>()
  for (const r of rows) {
    const kv = pick(r)
    if (!kv || verParts(kv[1]).length === 0) continue
    const cur = best.get(kv[0])
    if (!cur || cmpVer(verParts(kv[1]), verParts(cur)) > 0) best.set(kv[0], kv[1])
  }
  return best
}

const runtimeOf = (r: ShapeRow): [string, string] | null =>
  r.runtime && r.runtime_version ? [r.runtime, r.runtime_version] : null
const baseOf = (r: ShapeRow): [string, string] | null => (r.base_image && r.base_tag ? [r.base_image, r.base_tag] : null)

function isOld(kv: [string, string] | null, newest: Map<string, string>): boolean {
  if (!kv) return false
  const top = newest.get(kv[0])
  return !!top && verParts(kv[1]).length > 0 && cmpVer(verParts(kv[1]), verParts(top)) < 0
}

function Ver({ text, old, newest }: { text: string; old: boolean; newest?: string }) {
  return old ? (
    <span className="ver ver--old" title={`최신(${newest})보다 오래됨`}>⚠ {text}</span>
  ) : (
    <span className="ver">{text}</span>
  )
}

function deployCell(c?: DeployCell) {
  if (!c) return <span className="muted">—</span>
  return (
    <>
      {PATH_LABEL[c.path] ?? c.path}
      {c.manual && <span className="muted"> · 수동</span>}
      {c.mismatch && (
        <span className="badge badge--warn" style={{ marginLeft: 6 }} title="compose 파일과 판단이 다름">
          compose 다름
        </span>
      )}
    </>
  )
}

function execText(e?: ExecutorCell) {
  if (!e) return <span className="muted">—</span>
  return e.guess ? <span title="추정 — runners 표에 없는 태그">{e.value}?</span> : <>{e.value}</>
}

function envText(r: ShapeRow) {
  if (r.env_keys == null) return <span className="muted">—</span>
  if (!r.env_changed_at) return <>{r.env_keys}개</>
  const days = Math.floor((Date.now() - new Date(r.env_changed_at).getTime()) / 86400000)
  return (
    <>
      {r.env_keys}개 · <span className="badge badge--warn">{days <= 0 ? '오늘' : `${days}일 전`} 변경</span>
    </>
  )
}

const runtimeLabel = (r: ShapeRow) => (r.runtime ? `${r.runtime}${r.runtime_version ? ` ${r.runtime_version}` : ''}` : '')

export default function CicdCompare() {
  const [rows, setRows] = useState<ShapeRow[] | null>(null)
  const [err, setErr] = useState(false)
  const [runtime, setRuntime] = useState('')

  useEffect(() => {
    fetchShapes()
      .then((d) => setRows(Array.isArray(d) ? d : []))
      .catch(() => setErr(true))
  }, [])

  const all = rows ?? []
  const newestRuntime = newestBy(all, runtimeOf)
  const newestBase = newestBy(all, baseOf)
  const envs = ENV_ORDER.filter((e) => all.some((r) => r.deploy?.[e]))
  const runtimes = [...new Set(all.map(runtimeLabel).filter(Boolean))].sort()
  const shown = runtime ? all.filter((r) => runtimeLabel(r) === runtime) : all
  const oldCount = all.reduce(
    (n, r) => n + (isOld(runtimeOf(r), newestRuntime) ? 1 : 0) + (isOld(baseOf(r), newestBase) ? 1 : 0),
    0,
  )
  const latest = [...newestRuntime].map(([k, v]) => `${k} ${v}`).join(' · ')

  return (
    <div>
      <div className="subhead">서비스 비교</div>
      <div className="toolbar" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
        <select className="search" style={{ minWidth: 140 }} value={runtime} onChange={(e) => setRuntime(e.target.value)} aria-label="런타임 필터">
          <option value="">런타임: 전체</option>
          {runtimes.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
        {rows && rows.length > 0 && (
          <span className="muted" style={{ fontSize: 13 }}>
            <span className="ver ver--old">⚠ 빨간 칸</span> = 같은 종류 중 최신이 아닌 버전 ({oldCount}칸)
            {latest && ` · 최신: ${latest}`}
          </span>
        )}
      </div>

      <div className="card" style={{ overflowX: 'auto' }}>
        <table className="grid grid--nowrap">
          <thead>
            <tr>
              <th>서비스</th>
              <th>런타임</th>
              <th>베이스 이미지</th>
              {envs.map((e) => (
                <th key={e}>{e}</th>
              ))}
              <th>executor (repo / center)</th>
              <th>start.sh</th>
              <th>env</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const rt = runtimeOf(r)
              const base = baseOf(r)
              return (
                <tr key={r.service}>
                  <td>
                    {r.service}
                    {r.group && <span className="badge badge--muted" style={{ marginLeft: 6 }}>{r.group}</span>}
                  </td>
                  <td>
                    {r.runtime ? (
                      <Ver text={runtimeLabel(r)} old={isOld(rt, newestRuntime)} newest={rt ? `${rt[0]} ${newestRuntime.get(rt[0])}` : undefined} />
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    {r.base_image ? (
                      <Ver
                        text={`${r.base_image}${r.base_tag ? `:${r.base_tag}` : ''}`}
                        old={isOld(base, newestBase)}
                        newest={base ? `${base[0]}:${newestBase.get(base[0])}` : undefined}
                      />
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  {envs.map((e) => (
                    <td key={e}>{deployCell(r.deploy?.[e])}</td>
                  ))}
                  <td>
                    {execText(r.executor_repo)} / {execText(r.executor_center)}
                  </td>
                  <td>{r.startup == null ? <span className="muted">—</span> : r.startup ? '있음' : '없음'}</td>
                  <td>{envText(r)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {!rows && !err && <div className="placeholder" style={{ padding: '28px 16px' }}>불러오는 중…</div>}
        {rows && rows.length === 0 && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            아직 비교표가 없습니다 — <span className="mono">runner/shape-targets.example.yml</span> 을{' '}
            <span className="mono">shape-targets.yml</span> 로 복사해 채운 뒤:{' '}
            <span className="mono">python -m runner.cli shape</span>
          </div>
        )}
        {err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            비교표를 불러오지 못했습니다 — 중앙 API 상태를 확인하세요.
          </div>
        )}
      </div>
    </div>
  )
}
