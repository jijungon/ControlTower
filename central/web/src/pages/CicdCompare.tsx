import { Fragment, useEffect, useState } from 'react'
import { fetchShapes, type DeployCell, type ExecutorCell, type ShapeRow } from '../api'
import GroupFilter from '../components/GroupFilter'
import Legend, { type LegendRow } from '../components/Legend'
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

// job 이름 몇 개만(길면 '외 N개')
const jobNames = (jobs: string[]) => (jobs.length <= 2 ? jobs.join('·') : `${jobs.slice(0, 2).join('·')} 외 ${jobs.length - 2}개`)

// executor 한 칸 — job 별로 'build·build-manual: shell' 한 줄씩. 가장 많은 쪽은 '나머지 N개' 로 맨 아래.
// 줄마다 ▸ 를 누르면 아래로 펼쳐서 job 하나하나 + docker 면 쓰는 image
function ExecCell({ e, side }: { e?: ExecutorCell; side: 'repo' | 'center' }) {
  if (!e)
    return (
      <span className="muted" title={`${side} CI 를 안 읽음 — 대상 파일에 ${side}_ci 가 없거나(사본 없음) job 에 러너 태그가 없음`}>
        —
      </span>
    )
  // 같은 방식(+확정/추정)끼리 합침 — 러너 태그가 달라도 결과가 같으면 한 줄
  // images 가 아예 없는 그룹 = image 를 모으기 전의 옛 수집 → '없음' 이 아니라 '모름'
  const merged = new Map<
    string,
    {
      value: string
      guess: boolean
      jobs: string[]
      tags: string[]
      why: Set<string>
      images: Record<string, string>
      defaults: Record<string, string> // job → 러너 기본 이미지(로그에서, image: 없는 job)
      unknown: Set<string>
    }
  >()
  for (const g of e.groups?.length ? e.groups : [{ tag: (e.tags ?? []).join(', '), value: e.value, guess: e.guess, jobs: [] }]) {
    const k = `${g.value}|${g.guess}`
    const m = merged.get(k) ?? { value: g.value, guess: g.guess, jobs: [], tags: [], why: new Set<string>(), images: {}, defaults: {}, unknown: new Set<string>() }
    m.jobs.push(...g.jobs)
    if (g.default_image) g.jobs.forEach((j) => (m.defaults[j] = g.default_image!))
    if (!g.images) g.jobs.forEach((j) => m.unknown.add(j))
    Object.assign(m.images, g.images ?? {})
    m.tags.push(g.tag)
    if (g.why) m.why.add(g.why)
    merged.set(k, m)
  }
  const lines = [...merged.values()].sort((a, b) => a.jobs.length - b.jobs.length) // 적은 쪽 먼저, 가장 많은 쪽이 '나머지'
  const how = (m: { guess: boolean; why: Set<string> }) =>
    m.guess
      ? `추정(${[...m.why].join(', ')}) — GitLab 토큰을 넣으면 job 로그 맨 윗줄로 자동 확정(지금 직접 보려면 'Preparing the "shell|docker" executor' 를 보고 shape-targets.yml runners: 에 적기)`
      : `확정(${[...m.why].join(', ') || 'runners 표'})`
  return (
    <span className="exec-lines">
      {lines.map((m, i) => {
        const label = lines.length === 1 ? null : i === lines.length - 1 ? `나머지 ${m.jobs.length}개` : jobNames(m.jobs)
        const head = (
          <>
            {label && <span className="muted">{label}: </span>}
            <span className={m.guess ? 'muted' : undefined}>{m.value}</span>
            {m.guess && <small className="muted"> (추정)</small>}
          </>
        )
        const title = `${side} · job ${m.jobs.length}개 · 러너 태그: ${m.tags.join(' / ')}\n${how(m)}`
        if (m.jobs.length === 0)
          return (
            <span key={`${m.value}|${m.guess}`} className="exec-line" title={title}>
              {head}
            </span>
          )
        return (
          <details key={`${m.value}|${m.guess}`} className="exec-line exec-more">
            <summary title={title} aria-label={`${side} ${label ?? m.value} 펼치기`}>
              {head}
            </summary>
            <ul className="exec-jobs">
              {m.jobs.map((j) => (
                <li key={j}>
                  <span className="mono">{j}</span>
                  {m.images[j] ? (
                    <span className="muted"> · image </span>
                  ) : m.defaults[j] ? (
                    <span className="muted"> · image 없음 → 러너 기본 이미지 </span>
                  ) : m.unknown.has(j) ? (
                    <span className="muted" title="image 를 모으기 전의 데이터 — runner shape 로 다시 모으고 새로고침">
                      {' '}
                      · image 모름(다시 수집 필요)
                    </span>
                  ) : (
                    <span className="muted"> · image 없음{m.value === 'shell' ? '(러너 서버에서 바로)' : '(러너 기본 이미지)'}</span>
                  )}
                  {(m.images[j] || m.defaults[j]) && <span className="mono">{m.images[j] || m.defaults[j]}</span>}
                </li>
              ))}
            </ul>
          </details>
        )
      })}
    </span>
  )
}

// 표 읽는 법 — 칸마다 '무엇을 보여주나' + '값 → 뜻'(짧게)
const LEGEND: LegendRow[] = [
  {
    term: 'dev · stg · prod',
    what: '그 환경에 어떻게 배포하나',
    items: [
      ['이미지', '도커 이미지로 배포'],
      ['파일 복사', '결과물을 서버에 복사'],
      ['빌드만', '배포 안 함'],
      [<span className="muted">아랫줄 repo · center</span>, '누가 복사'],
      [<span className="muted">아랫줄 수동</span>, '버튼 눌러 배포'],
      [<span className="muted">아랫줄 compose 기준</span>, '서버 compose 로 짐작'],
    ],
  },
  { term: <span className="badge badge--warn">⚠ compose 다름</span>, what: 'CI 와 서버 compose 의 배포 모양이 다름' },
  {
    term: 'executor',
    what: 'job 을 어디서 돌리나 (job 이름: 방식)',
    items: [
      [<b>shell</b>, '러너가 깔린 서버에서 바로'],
      [<b>docker</b>, '그 서버 위 새 컨테이너 안에서'],
      [<small className="muted">(추정)</small>, '로그로 확인 못 함'],
      ['▸', 'job · image 보기'],
    ],
  },
]

// 러너 표 — 등록된 러너(태그)마다 방식 · 확정 근거 · GitLab 러너 이름 · 쓰는 서비스. 서비스 칸의 executor 를 태그로 모은 것
type RunnerInfo = {
  side: 'repo' | 'center'
  tag: string
  value: string
  guess: boolean
  why: string
  name?: string
  services: Set<string>
  jobs: number
}

export function collectRunners(rows: ShapeRow[]): RunnerInfo[] {
  const map = new Map<string, RunnerInfo>()
  for (const r of rows) {
    for (const side of ['repo', 'center'] as const) {
      for (const g of (side === 'repo' ? r.executor_repo : r.executor_center)?.groups ?? []) {
        const k = `${side}|${g.tag}`
        const cur = map.get(k)
        // 확정(로그·runners 표)이 하나라도 있으면 그걸로 — 추정보다 우선
        const better = !cur || (cur.guess && !g.guess)
        const info: RunnerInfo = better
          ? {
              side, tag: g.tag, value: g.value, guess: g.guess,
              why: g.why ?? (g.guess ? 'image: 유무로 짐작' : 'runners 표'), // 옛 수집엔 why 가 없음
              name: g.runner_name ?? cur?.name, services: cur?.services ?? new Set(), jobs: cur?.jobs ?? 0,
            }
          : cur!
        if (!info.name && g.runner_name) info.name = g.runner_name
        info.services.add(r.service)
        info.jobs += g.jobs.length
        map.set(k, info)
      }
    }
  }
  return [...map.values()].sort((a, b) => a.side.localeCompare(b.side) || b.jobs - a.jobs)
}

function RunnerTable({ rows }: { rows: ShapeRow[] }) {
  const runners = collectRunners(rows)
  if (runners.length === 0) return null
  return (
    <>
      <div className="section-head">
        <h2 className="section-title">러너</h2>
        <span className="section-sub">job 이 도는 곳 — CI 의 tags: 로 고른 러너마다</span>
      </div>
      <div className="card" style={{ overflowX: 'auto' }}>
        <table className="grid grid--dense">
          <thead>
            <tr>
              <th>GitLab</th>
              <th>러너 태그</th>
              <th>방식</th>
              <th>확인</th>
              <th>등록된 러너 이름</th>
              <th>쓰는 서비스</th>
            </tr>
          </thead>
          <tbody>
            {runners.map((x) => (
              <tr key={`${x.side}|${x.tag}`}>
                <td className="muted">{x.side}</td>
                <td className="mono" style={{ whiteSpace: 'nowrap' }}>{x.tag}</td>
                <td>
                  <b>{x.value}</b>
                </td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {x.guess ? (
                    <span className="muted" title="job 로그로 확인 못 함 — image: 가 있으면 docker, 없으면 shell 로 짐작">
                      추정 · {x.why}
                    </span>
                  ) : (
                    <span className="st-asis" style={{ fontWeight: 400 }}>
                      확정 · {x.why}
                    </span>
                  )}
                </td>
                <td className="mono">{x.name ?? <span className="muted">—</span>}</td>
                <td title={[...x.services].join(', ')}>
                  {[...x.services].slice(0, 3).join(', ')}
                  {x.services.size > 3 && <span className="muted"> 외 {x.services.size - 3}개</span>}
                  <span className="muted"> · job {x.jobs}개</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
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
        sub={rows ? `그룹 ${ordered.length} · 서비스 ${appCount}` : undefined}
        asOf={latestTime(all.map((r) => r.collected_at))}
        onRefresh={() => runAll(setBusy, [load])}
        busy={busy}
      />
      <Legend
        id="build"
        rows={LEGEND}
        source="repo·center GitLab(.gitlab-ci.yml · job 로그) + 서버 docker-compose — runner shape"
      />
      <div className="toolbar" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
        <GroupFilter groups={groupNames} value={groupSel} onChange={setGroupSel} />
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
              <th>executor · repo</th>
              <th>executor · center</th>
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
                            </td>
                          )}
                          <td>
                          {split(r).kind}
                          {r.note && <span className="cell-sub">{r.note}</span>}
                        </td>
                          {envs.map((e) => (
                            <td key={e}>{deployCell(r.deploy?.[e])}</td>
                          ))}
                          <td>
                            <ExecCell e={r.executor_repo} side="repo" />
                          </td>
                          <td>
                            <ExecCell e={r.executor_center} side="center" />
                          </td>
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

      <RunnerTable rows={all} />
    </div>
  )
}
