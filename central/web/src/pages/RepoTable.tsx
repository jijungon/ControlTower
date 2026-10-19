import { Fragment } from 'react'
import type { CodeVersions, RepoBuild, ShapeRow } from '../api'
import Legend, { type LegendRow } from '../components/Legend'
import { HostBadge } from './CicdCompare'
import { verParts } from '../vercmp'

// config 탭의 repo 보기 — 서비스마다 repo 프로젝트 · 빌드에 쓰는 런타임(repo CI 이미지) · 코드에 적힌 버전 · 실행 이미지(center) 비교

const major = (v?: string | null) => verParts(v)[0]

// 코드에 적힌 값(정확히 / 최소) 과 다른 버전 하나를 비교 — 다르면 true
function codeDiffers(code: CodeVersions, runtime: string, version?: string | null): boolean {
  const v = major(version)
  if (v === undefined) return false
  if (runtime === 'node' && code.node) {
    const c = major(code.node)!
    return code.node_rule === 'min' ? v < c : v !== c
  }
  if (runtime === 'java' && code.java) return v !== major(code.java)
  return false
}

const codeText = (c: CodeVersions) => (c.node ? `node ${c.node_rule === 'min' ? '≥' : ''}${c.node}` : c.java ? `java ${c.java}` : null)
const codeFrom = (c: CodeVersions) => (c.node ? c.node_from : (c.java_from ?? 'pom.xml'))

// 빨간 칸의 기준 — 코드에 적힌 값(사람이 정한 버전)이 있으면 코드, 없으면 실행 이미지(실제로 도는 것).
// 이 런타임·버전이 기준과 다르면 이유 문장, 같거나 비교할 수 없으면 null
function offBase(r: ShapeRow, runtime: string, version?: string | null, isRun = false): string | null {
  const code = r.repo?.code
  const codeT = code ? codeText(code) : null
  if (code && codeT && (runtime === 'node' ? code.node : runtime === 'java' ? code.java : null))
    return codeDiffers(code, runtime, version) ? `코드(${codeT}, ${codeFrom(code)})와 다름` : null
  if (isRun || !r.runtime || r.runtime !== runtime) return null // 코드가 없으면 실행이 기준 — 실행 칸 자신은 빨강 아님
  return major(version) !== major(r.runtime_version)
    ? `실행 이미지(${r.runtime} ${r.runtime_version})와 다름 — 코드에 적힌 버전이 없어 실행을 기준으로`
    : null
}

// 기준과 다르면 빨간 칸(center 보기의 '⚠ 빨간 칸'과 같은 모양)
function VerCell({ text, why, title }: { text: string; why: string | null; title?: string }) {
  return why ? (
    <span className="ver ver--old" title={`${why}${title ? `\n${title}` : ''}`}>
      ⚠ {text}
    </span>
  ) : (
    <span className="ver" title={title}>
      {text}
    </span>
  )
}

// 빌드 값을 어디서 봤나 — CI 이미지, 아니면 job 로그(shell 러너)
const buildSrc = (b: RepoBuild) => (b.from === 'log' ? (b.guess ? '같은 러너 job 로그 · 추정' : 'job 로그') : `CI 이미지 ${b.image}`)
const buildTitle = (b: RepoBuild) =>
  b.from === 'log'
    ? b.guess
      ? `이 서비스의 build job 로그엔 버전 줄이 없어, 같은 러너(${b.runner ?? '?'})의 다른 job 로그 #${b.job} 에서 본 값 — 같은 서버의 ${b.runtime} 를 쓴다고 보고 추정`
      : `job 로그 #${b.job} (${b.jobs.join(', ')}) — CI 에 이미지가 없어 shell 러너(${b.runner ?? '?'}) 서버에 깔린 ${b.runtime} 로 빌드`
    : `CI 이미지 ${b.image} · job ${b.jobs.join(', ')}`

// 확인할 것 — 빌드(repo CI 이미지) · 코드 · 실행(center 이미지) 셋 중 다른 것. [짧은 글, 뜻]
export function repoChecks(r: ShapeRow): [string, string][] {
  const code = r.repo?.code
  const builds = (r.repo?.build ?? []).filter((b) => b.version)
  const out: [string, string][] = []
  const run = r.runtime && r.runtime_version ? `${r.runtime} ${r.runtime_version}` : null
  const codeT = code ? codeText(code) : null
  for (const b of builds) {
    if (code && codeT && codeDiffers(code, b.runtime, b.version))
      out.push(['빌드≠코드', `빌드는 ${b.runtime} ${b.version}(${buildSrc(b)}), 코드는 ${codeT}(${codeFrom(code)})`])
    if (run && r.runtime === b.runtime && major(b.version) !== major(r.runtime_version))
      out.push(['빌드≠실행', `빌드는 ${b.runtime} ${b.version}(${buildSrc(b)}), 실행 이미지는 ${run}`])
  }
  if (code && codeT && r.runtime && codeDiffers(code, r.runtime, r.runtime_version))
    out.push(['코드≠실행', `코드는 ${codeT}(${codeFrom(code)}), 실행 이미지는 ${run}`])
  return out
}

// repo 저장소가 없는 서비스 — 읽을 게 없으니 '—'
const NONE = (
  <span className="muted" title="repo 저장소가 없음 — 읽지 않음">
    —
  </span>
)

// 빈 칸은 '—' 대신 이유를 짧게 — 없는 것(안 적힘)과 못 읽은 것(빨간 '못 읽음')을 화면에서 바로 구분
function buildCell(r: ShapeRow) {
  const repo = r.repo
  if (repo?.missing) return NONE
  if (repo && repo.read === false)
    return (
      <span className="miss-fail st-fail" title="repo CI(.gitlab-ci.yml)를 못 읽음 — 프로젝트 경로·토큰 권한 확인">
        못 읽음
      </span>
    )
  const builds = repo?.build ?? []
  if (builds.length === 0) {
    const shell = (r.executor_repo?.groups ?? []).some((g) => g.value === 'shell') || r.executor_repo?.value === 'shell'
    return (
      <span
        className="muted empty-why"
        title={
          shell
            ? 'repo CI job 에 image: 가 없어 shell 러너 서버에 깔린 node·java 로 빌드 — 버전은 GitLab 파일로 알 수 없음 (build job 에 node -v 를 넣으면 job 로그로 읽을 수 있음)'
            : 'repo CI job 에 런타임 이미지(node·java 등)가 없음 — Dockerfile 안에서 빌드하거나 러너 기본 이미지로 빌드'
        }
      >
        CI 에 없음{shell ? ' (shell)' : ''}
      </span>
    )
  }
  return (
    <span className="exec-lines">
      {builds.map((b: RepoBuild) => {
        const text = `${b.runtime}${b.version ? ` ${b.version}` : ''}`
        return (
          <span key={`${b.runtime}${b.version}`} className="exec-line">
            <VerCell text={text} why={offBase(r, b.runtime, b.version)} title={buildTitle(b)} />
            {b.from === 'log' && <small className="muted"> ({b.guess ? '추정' : '로그'})</small>}
          </span>
        )
      })}
    </span>
  )
}

function codeCell(r: ShapeRow) {
  if (r.repo?.missing) return NONE
  const c = r.repo?.code
  const t = c ? codeText(c) : null
  if (!c || !t)
    return (
      <span className="muted empty-why" title="repo 에 .nvmrc · package.json engines · pom.xml · build.gradle 버전이 안 적혀 있음 (읽기는 됐음)">
        안 적힘
      </span>
    )
  return (
    <span className="ver" title={`출처: ${codeFrom(c)}${c.nest ? ` · nest ${c.nest}` : ''}`}>
      {t}
    </span>
  )
}

function runCell(r: ShapeRow) {
  if (!r.runtime) return <span className="muted" title="이 서비스와 연결된 config 폴더(Dockerfile)가 없음">—</span>
  const text = `${r.runtime}${r.runtime_version ? ` ${r.runtime_version}` : ''}`
  return <VerCell text={text} why={offBase(r, r.runtime, r.runtime_version, true)} title="center config 의 Dockerfile FROM" />
}

function checkCell(r: ShapeRow) {
  if (r.repo?.missing) return NONE
  const checks = repoChecks(r)
  if (checks.length === 0) return <span className="badge badge--ok">없음</span>
  return (
    <span className="exec-lines">
      {checks.map(([label, why]) => (
        <span key={label} className="exec-line">
          <span className="badge badge--warn" title={why}>
            ⚠ {label}
          </span>
        </span>
      ))}
    </span>
  )
}

// 'g/sub/project' — '/' 에서만 줄바꿈(칸이 넓어지지 않게)
function ProjectPath({ path }: { path: string }) {
  return (
    <span className="mono grp-repo" title={`repo 프로젝트: ${path} (GitLab)`}>
      {path.split('/').map((part, i, arr) => (
        <span key={i} className="grp-repo-part">
          {part}
          {i < arr.length - 1 ? '/' : ''}
        </span>
      ))}
    </span>
  )
}

export const REPO_LEGEND: LegendRow[] = [
  {
    term: 'node · java 버전',
    what: '빌드 → 코드 → 실행 순서로 비교, 기준과 다르면 빨간 칸',
    items: [
      ['빌드', 'repo CI job 의 이미지(node:20-slim 등)'],
      ['코드', '.nvmrc · package.json · pom.xml · build.gradle'],
      ['실행', 'center 가 만든 이미지(Dockerfile FROM)'],
      [<span className="ver ver--old">⚠ node 20</span>, '기준과 다름 (기준 = 코드, 없으면 실행)'],
      [
        <>
          <span className="ver">node 20.15.1</span>
          <small className="muted"> (로그)</small>
        </>,
        'shell 러너라 job 로그에서 읽음 · (추정) = 같은 러너 값',
      ],
      [<span className="muted">CI 에 없음 (shell)</span>, '로그에도 버전 없음'],
      [<span className="muted">안 적힘</span>, '코드에 버전 없음'],
      [<span className="muted">repo 없음</span>, '저장소가 없어 안 읽음'],
      [<span className="miss-fail st-fail">못 읽음</span>, '읽기 실패'],
    ],
  },
  {
    term: '확인할 것',
    what: '셋 중 다른 것',
    items: [
      [<span className="badge badge--warn">⚠ 빌드≠코드</span>, 'CI 가 다른 버전으로 빌드'],
      [<span className="badge badge--warn">⚠ 빌드≠실행</span>, '빌드와 실행 버전이 다름'],
      [<span className="badge badge--warn">⚠ 코드≠실행</span>, '코드가 바라는 버전과 다름'],
      [<span className="badge badge--ok">없음</span>, '모두 같음'],
    ],
  },
]

export default function RepoTable({ rows }: { rows: ShapeRow[] }) {
  // 그룹 → 서비스 → 타입 (빌드·배포 표와 같은 묶음)
  const split = (r: ShapeRow) => {
    const t = r.type ?? ''
    return t && r.service.endsWith(` ${t}`) ? { app: r.service.slice(0, -t.length - 1), kind: t } : { app: r.service, kind: t || '—' }
  }
  const byGroup = new Map<string, Map<string, ShapeRow[]>>()
  for (const r of rows) {
    const g = r.group || '기타'
    const apps = byGroup.get(g) ?? new Map<string, ShapeRow[]>()
    apps.set(split(r).app, [...(apps.get(split(r).app) ?? []), r])
    byGroup.set(g, apps)
  }
  const ordered = [...byGroup.entries()]
    .sort(([a], [b]) => (a === '기타' ? 1 : b === '기타' ? -1 : a.localeCompare(b)))
    .map(([group, apps]) => ({
      group,
      // 서비스 안에서는 repo 프로젝트끼리 붙여 둠 → 같은 프로젝트는 한 칸(예: manager·syncer 가 repo 하나)
      apps: [...apps.entries()]
        .map(([app, rs]): [string, ShapeRow[]] => [app, [...rs].sort((a, b) => (a.repo?.project ?? '').localeCompare(b.repo?.project ?? '') || split(a).kind.localeCompare(split(b).kind))])
        .sort(([a], [b]) => a.localeCompare(b)),
    }))
  // 같은 repo 프로젝트가 이어지는 줄 수(첫 줄에만 칸을 그리고 아래로 합침), 이어지는 줄은 0
  const projectSpan = (rs: ShapeRow[], i: number) => {
    const p = rs[i].repo?.project ?? ''
    if (i > 0 && (rs[i - 1].repo?.project ?? '') === p) return 0
    let n = 1
    while (i + n < rs.length && (rs[i + n].repo?.project ?? '') === p) n++
    return n
  }

  return (
    <table className="grid grid--nowrap grid--dense">
      <thead>
        <tr className="th-band">
          <th rowSpan={2}>그룹</th>
          <th rowSpan={2}>서비스</th>
          <th rowSpan={2}>repo 프로젝트</th>
          <th rowSpan={2}>타입</th>
          <th colSpan={3} className="th-group">
            node · java 버전
            <span className="th-flow">repo CI 로 빌드 → 코드에 적힌 값 → center 이미지로 실행</span>
          </th>
          <th rowSpan={2}>확인할 것</th>
        </tr>
        <tr>
          <th className="th-sub">빌드 (repo CI 이미지)</th>
          <th className="th-sub">코드에 적힌 버전</th>
          <th className="th-sub">실행 (center 이미지)</th>
        </tr>
      </thead>
      <tbody>
        {ordered.map((g) => {
          const total = g.apps.reduce((n, [, rs]) => n + rs.length, 0)
          return (
            <Fragment key={g.group}>
              {g.apps.map(([app, rs], ai) =>
                rs.map((r, i) => {
                  const groupFirst = ai === 0 && i === 0
                  return (
                    <tr key={r.service} className={groupFirst ? 'grp-start' : i === 0 ? 'svc-start' : undefined}>
                      {groupFirst && (
                        <td className="grp-cell" rowSpan={total}>
                          {g.group}
                          <div className="muted" style={{ fontWeight: 400, fontSize: 12 }}>
                            서비스 {g.apps.length}개
                          </div>
                          <div className="grp-host">
                            <HostBadge host="gitlab" />
                          </div>
                        </td>
                      )}
                      {i === 0 && (
                        <td className="svc-cell" rowSpan={rs.length}>
                          {app}
                        </td>
                      )}
                      {projectSpan(rs, i) > 0 && (
                        <td rowSpan={projectSpan(rs, i)}>
                          {r.repo?.project ? (
                            <>
                              <ProjectPath path={r.repo.project} />
                              {r.repo.kept && (
                                <span className="cell-tag" title="이번 수집은 repo GitLab 에 접속이 안 됨 — 이 줄의 빌드·코드 버전은 지난 수집 값">
                                  지난 값
                                </span>
                              )}
                            </>
                          ) : r.repo?.missing ? (
                            <span className="muted empty-why" title="repo 저장소가 없음(없어짐) — 읽지 않음, 실행 이미지만 center 에서">
                              repo 없음
                            </span>
                          ) : (
                            <span className="muted empty-why" title="대상 파일에 repo: 프로젝트를 안 적음 — 로컬 사본을 읽음">
                              안 적음
                            </span>
                          )}
                        </td>
                      )}
                      <td>{split(r).kind}</td>
                      <td>{buildCell(r)}</td>
                      <td>{codeCell(r)}</td>
                      <td>{runCell(r)}</td>
                      <td>{checkCell(r)}</td>
                    </tr>
                  )
                }),
              )}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}

export function RepoLegend() {
  return (
    <Legend
      id="config-repo"
      rows={REPO_LEGEND}
      source="repo GitLab(.gitlab-ci.yml · .nvmrc · package.json · pom.xml · build.gradle) + center config repo(Dockerfile) — runner shape"
    />
  )
}
