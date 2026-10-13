import { Fragment, useEffect, useState } from 'react'
import { fetchShapes, type DeployCell, type ExecutorCell, type ShapeRow } from '../api'
import SectionHead, { latestTime, runAll } from '../components/SectionHead'

// 환경 칸 순서(데이터에 있는 환경만 보인다)
const ENV_ORDER = ['dev', 'lab', 'stg', 'preview', 'prod']
const TYPE_ORDER = ['web', 'was']

// 배포 칸 — 짧은 글자 + 마우스를 올리면 뜻
const PATH: Record<string, { label: string; sub?: string; title: string }> = {
  'direct:repo': { label: '파일 복사', sub: 'repo', title: '예전 직배포 — repo CI 가 빌드 결과물을 서버로 바로 복사 (center 를 안 거침, 옮길 대상)' },
  'direct:center': { label: '파일 복사', sub: 'center', title: 'repo 가 center 로 넘기고, center CI 가 빌드 결과물을 서버로 복사 (이미지는 안 만듦)' },
  image: { label: '이미지', title: 'center 가 만든 도커 이미지를 서버가 받아서 실행' },
  build: { label: '빌드만', title: '빌드만 하고 배포는 안 함' },
  'direct:compose': { label: '파일 복사', sub: 'compose 기준', title: 'CI 에는 이 환경 배포가 없어서, 서버 compose 모양(베이스 이미지 + 폴더 마운트)으로 짐작 — 손으로 배포하는 곳일 수 있음' },
  'image:compose': { label: '이미지', sub: 'compose 기준', title: 'CI 에는 이 환경 배포가 없어서, 서버 compose 모양(서비스 이미지 태그)으로 짐작' },
}
const pathKey = (c: DeployCell) =>
  c.by === 'compose' ? `${c.path}:compose` : c.path === 'direct' ? `direct:${c.by ?? 'repo'}` : c.path

// "shop web" + type web → 서비스 "shop", 타입 "web"
function split(r: ShapeRow): { app: string; kind: string } {
  const t = r.type ?? ''
  if (t && r.service.endsWith(` ${t}`)) return { app: r.service.slice(0, -t.length - 1), kind: t }
  return { app: r.service, kind: t || '—' }
}

function deployCell(c?: DeployCell) {
  if (!c) return <span className="muted">—</span>
  const p = PATH[pathKey(c)] ?? { label: c.path, title: '' }
  const other = c.path === 'image' ? '파일 복사(베이스 이미지 + 폴더 마운트)' : '이미지(서비스 이미지 태그)'
  const sub = [p.sub, c.manual ? '수동' : null].filter(Boolean).join(' · ')
  return (
    <span title={`${p.title}${c.manual ? ' · 수동: 사람이 GitLab 에서 버튼을 눌러야 배포' : ''}`}>
      {p.label}
      {c.mismatch && (
        <span
          className="badge badge--warn"
          style={{ marginLeft: 4 }}
          title={`CI 파일은 '${p.label}' 인데, 서버 compose 파일은 ${other} 모양이에요 — 둘 중 하나가 옛날 상태`}
        >
          ⚠ compose 다름
        </span>
      )}
      {sub && <span className="cell-sub">{sub}</span>}
    </span>
  )
}

function execText(e?: ExecutorCell) {
  if (!e) return <span className="muted">—</span>
  if (!e.guess) return <span title={e.tags?.length ? `러너 태그: ${e.tags.join(', ')}` : undefined}>{e.value}</span>
  return (
    <span
      className="muted"
      title={`러너 태그(${(e.tags ?? []).join(', ') || '없음'})가 runners 표에 없어 짐작한 값 — 확인되면 shape-targets.yml 의 runners: 에 적으면 확정돼요`}
    >
      {e.value}
      <small> (추정)</small>
    </span>
  )
}

function envText(r: ShapeRow) {
  if (r.env_keys == null) return <span className="muted">—</span>
  const base = <span title=".gitlab-ci.yml(repo·center) 의 variables: 개수 — 값은 안 보고 '바뀌었는지'만 봐요">{r.env_keys}개</span>
  if (!r.env_changed_at) return base
  const days = Math.floor((Date.now() - new Date(r.env_changed_at).getTime()) / 86400000)
  return (
    <>
      {base} <span className="badge badge--warn">{days <= 0 ? '오늘' : `${days}일 전`} 바뀜</span>
    </>
  )
}

function Legend() {
  return (
    <details className="legend" open>
      <summary>표 읽는 법</summary>
      <ul>
        <li>
          <b>dev · stg · prod 칸</b> = 그 환경에 어떻게 배포하나. 윗줄은 방식, 아랫줄은 누가 — <b>파일 복사 / repo</b>(예전 직배포: repo 가 서버에 바로 복사, 옮길 대상) ·{' '}
          <b>파일 복사 / center</b>(center 를 거쳐 파일로 복사, 이미지 안 만듦) · <b>이미지</b>(center 가 만든 도커 이미지로 배포) ·{' '}
          <b>빌드만</b>(배포 안 함) · <b>수동</b>(사람이 버튼을 눌러야 함) · <b>compose 기준</b>(CI 에 없어서 서버 compose 로 짐작)
        </li>
        <li>
          <b>⚠ compose 다름</b> = CI 파일에 적힌 배포 방식과 서버의 docker-compose 모양이 서로 달라요 (예: CI 는 이미지인데 서버는 아직 파일 복사 방식)
        </li>
        <li>
          <b>executor</b> = CI 를 돌리는 방식 — <b>shell</b>(러너 서버에서 바로) · <b>docker</b>(깨끗한 컨테이너 안에서). <b>(추정)</b> = 확인 안 된 짐작값(마우스를 올리면 이유)
        </li>
        <li>
          <b>CI 변수</b> = .gitlab-ci.yml 의 변수 개수. 값은 보지 않고, 바뀌면 "N일 전 바뀜"
        </li>
        <li className="muted">런타임·베이스 이미지·start.sh 는 <b>config</b> 탭에서 봐요 (이 표는 CI 가 어떻게 빌드·배포하나만)</li>
      </ul>
    </details>
  )
}

export default function CicdCompare() {
  const [rows, setRows] = useState<ShapeRow[] | null>(null)
  const [err, setErr] = useState(false)
  const [groupSel, setGroupSel] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () =>
    fetchShapes()
      .then((d) => {
        setRows(Array.isArray(d) ? d : [])
        setErr(false)
      })
      .catch(() => setErr(true))

  useEffect(() => {
    load()
  }, [])

  const all = rows ?? []
  const envs = ENV_ORDER.filter((e) => all.some((r) => r.deploy?.[e]))
  // 그룹(프로젝트 묶음) → 서비스 → 타입(web·was) 으로 묶기
  const typeRank = (r: ShapeRow) => {
    const i = TYPE_ORDER.indexOf(split(r).kind)
    return i < 0 ? 99 : i
  }
  const byGroup = new Map<string, Map<string, ShapeRow[]>>()
  for (const r of all.filter((x) => !groupSel || (x.group || '기타') === groupSel)) {
    const g = r.group || '기타'
    const apps = byGroup.get(g) ?? new Map<string, ShapeRow[]>()
    apps.set(split(r).app, [...(apps.get(split(r).app) ?? []), r])
    byGroup.set(g, apps)
  }
  const ordered = [...byGroup.entries()]
    .sort(([a], [b]) => (a === '기타' ? 1 : b === '기타' ? -1 : a.localeCompare(b)))
    .map(([group, apps]) => ({
      group,
      apps: [...apps.entries()]
        .map(([app, rs]) => ({ app, rows: [...rs].sort((a, b) => typeRank(a) - typeRank(b)) }))
        .sort((a, b) => a.app.localeCompare(b.app)),
    }))
  const groupNames = [...new Set(all.map((r) => r.group || '기타'))].sort()
  const appCount = ordered.reduce((n, g) => n + g.apps.length, 0)

  return (
    <div>
      <SectionHead
        title="서비스 비교"
        sub={rows ? `CI 가 어떻게 빌드·배포하나 · 그룹 ${ordered.length}개 · 서비스 ${appCount}개` : undefined}
        asOf={latestTime(all.map((r) => r.collected_at))}
        onRefresh={() => runAll(setBusy, [load])}
        busy={busy}
        source="repo·center 의 .gitlab-ci.yml (+ 서버 docker-compose 로 확인) · 수집 python -m runner.cli shape · 대상 shape-targets.yml"
      />
      <Legend />
      <div className="toolbar" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
        <select className="search" style={{ minWidth: 140 }} value={groupSel} onChange={(e) => setGroupSel(e.target.value)} aria-label="그룹 필터">
          <option value="">그룹: 전체</option>
          {groupNames.map((g) => (
            <option key={g} value={g}>{g}</option>
          ))}
        </select>
      </div>

      <div className="card" style={{ overflowX: 'auto' }}>
        <table className="grid grid--nowrap grid--dense">
          <thead>
            <tr>
              <th>그룹</th>
              <th>서비스</th>
              <th>타입</th>
              {envs.map((e) => (
                <th key={e}>{e}</th>
              ))}
              <th>executor (repo / center)</th>
              <th>CI 변수</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((g) => {
              const total = g.apps.reduce((n, a) => n + a.rows.length, 0)
              return (
                <Fragment key={g.group}>
                  {g.apps.map((a, ai) =>
                    a.rows.map((r, i) => {
                      const groupFirst = ai === 0 && i === 0
                      // 경계: 그룹이 바뀌면 진한 선, 서비스가 바뀌면 보통 선, 타입끼리는 얇은 선
                      return (
                        <tr key={r.service} className={groupFirst ? 'grp-start' : i === 0 ? 'svc-start' : undefined}>
                          {groupFirst && (
                            <td className="grp-cell" rowSpan={total}>
                              {g.group}
                              <div className="muted" style={{ fontWeight: 400, fontSize: 12 }}>
                                서비스 {g.apps.length}개
                              </div>
                            </td>
                          )}
                          {i === 0 && (
                            <td className="svc-cell" rowSpan={a.rows.length}>
                              {a.app}
                              {r.note && (
                                <div className="muted" style={{ fontWeight: 400, fontSize: 12 }}>
                                  {r.note}
                                </div>
                              )}
                            </td>
                          )}
                          <td>{split(r).kind}</td>
                          {envs.map((e) => (
                            <td key={e}>{deployCell(r.deploy?.[e])}</td>
                          ))}
                          <td>
                            {execText(r.executor_repo)} / {execText(r.executor_center)}
                          </td>
                          <td>{envText(r)}</td>
                        </tr>
                      )
                    }),
                  )}
                </Fragment>
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
