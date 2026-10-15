import { Fragment, useEffect, useState } from 'react'
import { fetchConfig, fetchShapes, type ComposeSrc, type ConfigRow, type ShapeRow } from '../api'
import CollectButton from '../components/CollectButton'
import GroupFilter from '../components/GroupFilter'
import Legend, { type LegendRow } from '../components/Legend'
import SectionHead, { latestTime } from '../components/SectionHead'
import { isOld, newestBy, Ver, verParts } from '../vercmp'
import RepoTable, { RepoLegend, repoChecks } from './RepoTable'

// 처음 실행할 명령 = 컨테이너가 켜질 때 앱을 띄우는 명령이 어디 있나. 모든 칸이 이 말 하나만 쓴다.
type Run = 'start.sh' | 'cmd' | 'compose' | 'base' | 'server'
const RUN: Record<Run, { label: string; tone: string; title: string }> = {
  'start.sh': { label: 'start.sh', tone: 'warn', title: 'start.sh 스크립트가 앱을 띄움' },
  cmd: { label: 'Dockerfile CMD', tone: 'ok', title: 'Dockerfile 안의 CMD 가 앱을 띄움 — start.sh 필요 없음' },
  compose: { label: '서버 compose', tone: 'ok', title: '서버 docker-compose 의 command: 가 앱을 띄움 — start.sh 필요 없음' },
  base: { label: '베이스 이미지', tone: 'muted', title: '베이스 이미지가 알아서 띄움 — 예: springboot 이미지가 SPRING_FILE(jar) 을 실행, start.sh 안 씀' },
  server: { label: '없음 → 서버가 줌', tone: 'warn', title: 'Dockerfile 에 CMD 도 없고 start.sh 도 안 넣음 — 이미지 혼자서는 못 띄우고 서버 compose 가 명령을 줘야 함' },
}

// 이미지 기준(config 의 Dockerfile 만 봤을 때)
function imageRun(r: ConfigRow): Run | null {
  switch (r.start) {
    case 'dockerfile': return 'cmd'
    case 'start.sh': return 'start.sh'
    case 'server': return 'server'
    case 'base': return 'base'
    default: return null
  }
}

// 서버 기준(환경별) — compose 가 명령을 주면 그게 이기고, 아무것도 없으면 이미지 기준을 그대로 씀
function serverRun(r: ConfigRow, env: string): Run | null {
  const c = r.compose?.[env]
  if (c === 'command') return 'compose'
  if (c === 'mount') return 'start.sh'
  return imageRun(r)
}

// 정리할 것 — '처음 실행할 명령' 기준으로 다음에 할 일
const TODO: Record<ConfigRow['state'], { label: string; tone: string; title: string }> = {
  legacy: { label: 'CMD 로 옮기기', tone: 'danger', title: '지금은 start.sh 가 앱을 띄움 — Dockerfile 에 CMD 를 넣고 start.sh 를 없애면 끝' },
  leftover: { label: 'start.sh 지우기', tone: 'warn', title: '이미 Dockerfile CMD 가 앱을 띄움 — 폴더에 남은 start.sh 는 안 쓰임' },
  server: { label: 'CMD 넣기', tone: 'warn', title: '지금은 서버 compose 가 명령을 줌 — 이미지 혼자 뜨도록 CMD 를 넣으면 깔끔' },
  done: { label: '없음', tone: 'ok', title: 'Dockerfile CMD 로 뜨고 start.sh 도 없음' },
  base: { label: '없음', tone: 'ok', title: '베이스 이미지가 앱을 띄움(예: springboot 가 jar 실행) — start.sh 안 씀, 할 일 없음' },
  none: { label: 'Dockerfile 없음', tone: 'muted', title: '폴더에 Dockerfile 이 없음' },
}

function runBadge(run: Run | null, prefix = '') {
  if (!run) return <span className="muted">—</span>
  const m = RUN[run]
  return (
    <span className={`badge badge--${m.tone}`} title={m.title} style={{ marginRight: 4 }}>
      {prefix}
      {m.label}
    </span>
  )
}

const ENV_ORDER = ['dev', 'lab', 'stg', 'preview', 'prod']

// repo(서비스 — 빌드·코드) → center(config repo 폴더 — 이미지·실행) 보기, 흐름 순서대로. 고른 보기는 이 브라우저에만 기억
type Side = 'center' | 'repo'
const SIDES: [Side, string][] = [
  ['repo', 'repo'],
  ['center', 'center'],
]
const SIDE_KEY = 'ct.config.side'
function readSide(): Side {
  try {
    return localStorage.getItem(SIDE_KEY) === 'center' ? 'center' : 'repo'
  } catch {
    return 'repo'
  }
}

const runtimeOf = (r: ConfigRow): [string, string] | null =>
  r.runtime && r.runtime_version ? [r.runtime, r.runtime_version] : null
const baseOf = (r: ConfigRow): [string, string] | null => (r.base_image && r.base_tag ? [r.base_image, r.base_tag] : null)

// 코드에 적힌 버전 vs 이미지 런타임 — 다르면 이유 문장, 같으면 null
export function codeMismatch(r: ConfigRow): string | null {
  const c = r.code
  if (!c || !r.runtime || !r.runtime_version) return null
  const img = verParts(r.runtime_version)[0]
  if (r.runtime === 'node' && c.node) {
    const code = verParts(c.node)[0]
    const bad = c.node_rule === 'min' ? img < code : img !== code
    if (bad) return `코드는 node ${c.node_rule === 'min' ? '≥' : ''}${c.node}(${c.node_from}), 이미지는 node ${r.runtime_version}`
  }
  if (r.runtime === 'java' && c.java && verParts(c.java)[0] !== img) return `코드는 java ${c.java}(${c.java_from ?? 'pom.xml'}), 이미지는 java ${r.runtime_version}`
  return null
}

// 서버 compose 를 어디서 읽었나 — 칸 옆 작은 글씨. 서버 = 실서버에서 직접(SSH), 사본 = 복사해 둔 파일(다를 수 있음)
function srcLabel(info?: ComposeSrc | null): { text: string; title: string } | null {
  if (!info) return null
  if (info.kept) {  // 이번 수집은 GitLab 만 — 서버 compose 는 지난 수집 값
    const s = srcLabel({ ...info, kept: false })
    return s && { text: `${s.text} · 지난 값`, title: `${s.title}\n지난 수집 값 — 이번 수집은 GitLab 만 다시 읽음(서버 compose 는 SSH 로 안 읽음)` }
  }
  if (info.kind === 'ssh' && info.via) return { text: 'gw', title: `게이트웨이를 거쳐 실서버에서 읽음 (${info.where}) — center CI 의 배포 서버·폴더로 자동으로 찾음` }
  if (info.kind === 'ssh') return { text: info.auto ? '자동' : '서버', title: `실서버에서 SSH 로 읽음 (${info.where})${info.auto ? ' — center CI 의 배포 서버·폴더로 자동으로 찾음' : ''}` }
  if (info.kind === 'file') return { text: info.note || '사본', title: `복사해 둔 파일을 읽음 — 실서버와 다를 수 있음 (${info.where})` }
  if (info.kind === 'gitlab') return { text: 'GitLab', title: `GitLab 파일을 읽음 (${info.where})` }
  return null
}

// '못 읽음' 옆 짧은 이유 — 전체 이유는 마우스
export function missShort(reason: string): string {
  if (reason.includes('직접 등록 안 된')) return '직접 접속 안 됨'
  if (reason.includes('적어 둔 파일')) return '파일 못 읽음'
  if (/sudo:|sudoers/i.test(reason)) return 'sudo 안 됨'
  if (/Host key verification failed/i.test(reason)) return '서버 지문 모름'
  if (/Permission denied/i.test(reason)) return '권한 없음'
  if (/timed out|timeout|No route|unreachable/i.test(reason)) return '네트워크 안 닿음'
  if (/No such file/i.test(reason)) return '파일 없음'
  return 'SSH 실패'
}

// (서버) 환경 한 칸 — ● = 실제로 실행되는 명령
//   compose 가 command: 를 주거나 start.sh 를 넣으면 → 이 칸이 이김(●)
//   아무것도 안 하면 → (이미지) 칸의 명령이 그대로 실행 → '← 이미지'
//   칸 옆 작은 글씨 = 어디서 읽었나(서버 / 자동 / gw / 사본 / 옛 사본) — 모든 칸이 한 줄
function serverEnvCell(r: ConfigRow, env: string) {
  const c = r.compose?.[env]
  const m = r.compose_miss?.[env]
  // 다른 폴더로 합쳐져 안 쓰는 폴더 → 서버를 읽을 필요 없음
  if (!c && r.merged_into)
    return (
      <span className="muted" title={`이 폴더는 ${r.merged_into} 로 합쳐져 안 쓰여요 — 서버는 ${r.merged_into} 줄에서 봐요`}>
        —
      </span>
    )
  // 그 서비스가 이 환경엔 배포를 안 함(빌드·배포 표 기준) → 읽을 게 없음
  if (!c && m?.state !== 'fail' && r.deploy_envs?.length && !r.deploy_envs.includes(env))
    return (
      <span className="muted" title={`이 서비스는 ${env} 에 배포 안 함 (배포하는 환경: ${r.deploy_envs.join(', ')}) — 읽을 서버 없음`}>
        —
      </span>
    )
  // start.sh 를 아예 안 쓰는 이미지(예: springboot 가 jar 실행)는 서버를 안 읽어도 됨 → 할 일처럼 보이지 않게 '—'
  if (!c && r.start === 'base')
    return (
      <span className="muted" title="베이스 이미지가 앱을 띄워서(start.sh 안 씀) 서버 compose 를 읽을 필요 없음">
        —
      </span>
    )
  if (!c) {
    if (m?.state === 'fail')
      return (
        <span title={`못 읽음 — ${m.reason}`}>
          <span className="miss-fail st-fail">못 읽음</span>
          <span className="cell-tag miss-fail">{missShort(m.reason)}</span>
        </span>
      )
    return (
      <span title={m?.state === 'planned' ? `안 읽음 (위치는 찾음) — ${m.reason}` : `${env} 서버 compose 를 아직 읽으려고 하지 않음 — runner shape --ssh 로 실서버에서 읽거나 대상 파일에 적으면 표시`}>
        <span className="st-unread">안 읽음</span>
      </span>
    )
  }
  const src = srcLabel(r.compose_src?.[env])
  if (c === 'image')
    return (
      <span title={`${env} 서버는 compose 에 실행 명령이 없어서 (이미지) 칸의 명령이 그대로 실행돼요${src ? ` · 출처: ${src.title}` : ''}`}>
        <span className="st-asis">← 이미지</span>
        {src && <span className="cell-tag">{src.text}</span>}
      </span>
    )
  const run = serverRun(r, env)!
  const why = c === 'command' ? '서버 compose 의 command: 가 이미지 명령을 덮어씀' : '서버 compose 가 start.sh 를 넣어서(마운트) 그게 실행됨'
  return (
    <span title={`● 실제로 실행되는 명령 — ${why}${src ? ` · 출처: ${src.title}` : ''}`}>
      <span className="run-dot" aria-label="실행됨" />
      {runBadge(run)}
      {src && <span className="cell-tag">{src.text}</span>}
    </span>
  )
}

// '기타' 칸 — lab·preview 같은 환경을 한 줄에 이어서 짧게(자세한 건 마우스). 결과가 같은 환경은 묶음: 'lab·preview ● start.sh'
function extraCell(r: ConfigRow, extras: string[]) {
  const lines = r.start === 'base' ? extras.filter((e) => r.compose?.[e]) : extras.filter((e) => r.compose?.[e] || r.compose_miss?.[e])
  if (lines.length === 0) return <span className="muted">—</span>
  const groups = new Map<string, { envs: string[]; cls: string; titles: string[] }>()
  for (const e of lines) {
    const c = r.compose?.[e]
    const m = r.compose_miss?.[e]
    const text = c ? (c === 'image' ? '← 이미지' : `● ${RUN[serverRun(r, e)!].label}`) : m?.state === 'fail' ? '못 읽음' : '안 읽음'
    const src = srcLabel(r.compose_src?.[e])
    const g = groups.get(text) ?? { envs: [], cls: c ? (c === 'image' ? 'st-asis' : '') : m?.state === 'fail' ? 'miss-fail' : 'st-unread-text', titles: [] }
    g.envs.push(e)
    g.titles.push(c ? `${e}: ${text}${src ? ` · 출처: ${src.title}` : ''}` : `${e}: ${m?.reason ?? ''}`)
    groups.set(text, g)
  }
  // 환경 이름과 결과 사이에서만 줄바꿈(좁은 화면)
  return [...groups.entries()].map(([text, g], i) => (
    <Fragment key={text}>
      {i > 0 && <span className="muted"> · </span>}
      <span className={`extra-line ${g.cls}`} title={g.titles.join('\n')}>
        <span className="muted extra-part">{g.envs.join('·')}</span> <span className="extra-part">{text}</span>
      </span>
    </Fragment>
  ))
}

// (이미지) 칸 — ● = 이 명령을 그대로 실행하는 서버가 있음(어디인지는 마우스) · 흐림 = 읽은 서버가 모두 덮어써서 안 쓰임
function imageCell(r: ConfigRow, envs: string[]) {
  const run = imageRun(r)
  if (!run) return <span className="muted">—</span>
  const known = envs.filter((e) => r.compose?.[e])
  const asIs = known.filter((e) => r.compose?.[e] === 'image')
  const unused = asIs.length === 0 && known.length > 0
  const title = asIs.length > 0 ? `이 명령을 그대로 실행하는 서버: ${asIs.join(', ')}` : unused ? '서버에선 안 씀 — 읽은 서버는 모두 compose 가 덮어써요' : undefined
  return (
    <span title={title} className={unused ? 'run-unused' : undefined}>
      {asIs.length > 0 && <span className="run-dot" aria-label="실행됨" />}
      {runBadge(run)}
    </span>
  )
}

// 타입 칸 — 보통 폴더 이름. 이미지 하나를 역할별로 나눠 띄우면(예: manager·syncer) 역할마다 한 줄 + 옆에 실제 폴더
function typeCell(r: ConfigRow) {
  const type = r.path.split('/')[1]
  if (!type) return <span className="muted">—</span>
  if (!r.folder) return type
  const folder = r.folder.split('/')[1] ?? r.folder
  return (
    <span title={`config 폴더는 ${r.folder} — 같은 이미지를 서버 compose 의 command: 로 역할(${type})만 바꿔 띄워요`}>
      {type}
      <span className="cell-tag type-roles"> ({folder})</span>
    </span>
  )
}

// ▸ 펼치면: 환경 | 처음 실행할 명령 | 어디서 읽었나 | 위치·이유 — 칸에선 마우스로만 보이던 것을 열 맞춘 표로
function envDetail(r: ConfigRow, envList: string[]) {
  const img = imageRun(r)
  const row = (env: string): [string, string, string] => {
    const c = r.compose?.[env]
    const m = r.compose_miss?.[env]
    const info = r.compose_src?.[env]
    const from = srcLabel(info)?.text ?? '—'
    if (c === 'image') return [`← 이미지 (${img ? RUN[img].label : '—'})`, from, info?.where ?? '']
    if (c) return [`${RUN[serverRun(r, env)!].label} — ${c === 'command' ? 'compose 가 덮어씀' : 'start.sh 넣음'}`, from, info?.where ?? '']
    if (r.merged_into) return ['—', '—', `${r.merged_into} 로 합쳐져 안 씀`]
    if (r.start === 'base') return ['—', '—', '베이스 이미지가 띄움 — 서버를 읽을 필요 없음']
    if (m?.state === 'fail') return ['못 읽음', '—', m.reason]
    if (r.deploy_envs?.length && !r.deploy_envs.includes(env)) return ['—', '—', '이 환경엔 배포 안 함']
    return ['안 읽음', '—', m?.reason ?? '아직 서버를 안 봄']
  }
  return (
    <table className="mini-table">
      <thead>
        <tr>
          <th>환경</th>
          <th>처음 실행할 명령</th>
          <th>어디서 읽었나</th>
          <th>위치 · 이유</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td className="muted">(이미지)</td>
          <td>{img ? RUN[img].label : '—'}</td>
          <td>config repo</td>
          <td className="mono">{r.folder ?? r.path}/</td>
        </tr>
        {envList.map((e) => {
          const [run, from, detail] = row(e)
          return (
            <tr key={e}>
              <td>{e}</td>
              <td>{run}</td>
              <td>{from}</td>
              <td className="mono">{detail}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function todoCell(r: ConfigRow) {
  if (r.merged_into)
    return (
      <span className="badge badge--muted" title={`이 폴더는 ${r.merged_into} 로 합쳐져 안 쓰여요 — 대상 파일의 config.merged`}>
        {`합쳐짐 → ${r.merged_into}`}
      </span>
    )
  if (r.state === 'base')
    return (
      <span className="badge badge--muted" title={TODO.base.title}>
        {r.runtime === 'java' ? 'java' : '베이스 이미지'} 라 start.sh 안 씀
      </span>
    )
  const t = TODO[r.state] ?? TODO.none
  if (t.label === '—') return <span className="muted" title={t.title}>—</span>
  const files = r.start_files?.length ? ` · 폴더의 파일: ${r.start_files.join(', ')}` : ''
  return (
    <span className={`badge badge--${t.tone}`} title={`${t.title}${files}`}>
      {t.label}
    </span>
  )
}

// 표 읽는 법 — 칸마다 '무엇을 보여주나' + '값 → 뜻'(짧게)
const LEGEND: LegendRow[] = [
  {
    term: '버전',
    what: '이미지 런타임 · FROM 이미지 비교 (코드에 적힌 버전은 repo 보기)',
    items: [[<span className="ver ver--old">⚠ 빨간 칸</span>, '최신 아님']],
  },
  {
    term: '처음 실행할 명령',
    what: '앱을 띄우는 명령이 어디 있나',
    items: [
      [<span className="badge badge--warn">start.sh</span>, '별도 스크립트'],
      [<span className="badge badge--ok">Dockerfile CMD</span>, '이미지 안'],
      [<span className="badge badge--ok">서버 compose</span>, '서버 command:'],
      [<span className="badge badge--muted">베이스 이미지</span>, 'java 가 jar 실행'],
      [<span className="badge badge--warn">없음 → 서버가 줌</span>, '이미지 혼자 못 띄움'],
    ],
  },
  {
    term: '(이미지) 칸',
    what: 'Dockerfile 이 넣어 둔 명령',
    items: [
      [<span className="run-dot" />, '그대로 쓰는 서버 있음'],
      [
        <span className="run-unused">
          <span className="badge badge--warn">흐린 배지</span>
        </span>,
        '서버가 다 덮어씀',
      ],
    ],
  },
  {
    term: '(서버) 칸',
    what: '그 서버에서 실제로 뜨는 명령',
    items: [
      [
        <>
          <span className="run-dot" />
          <span className="badge badge--ok">서버 compose</span>
        </>,
        '덮어써서 실행',
      ],
      [<span className="st-asis">← 이미지</span>, '이미지 명령 그대로'],
      [<span className="st-unread">안 읽음</span>, '아직 안 봄'],
      [<span className="miss-fail st-fail">못 읽음</span>, '읽기 실패'],
      [<span className="muted">—</span>, '읽을 게 없음'],
      [<span className="cell-tag">gw · 사본</span>, '어디서 읽었나'],
    ],
  },
  {
    term: '정리할 것',
    what: '다음에 할 일',
    items: [
      [<span className="badge badge--danger">CMD 로 옮기기</span>, 'start.sh → CMD'],
      [<span className="badge badge--warn">start.sh 지우기</span>, '남은 파일만'],
      [<span className="badge badge--warn">CMD 넣기</span>, '이미지에 CMD'],
      [<span className="badge badge--ok">없음</span>, '끝'],
      [<span className="badge badge--muted">java 라 start.sh 안 씀</span>, '해당 없음'],
      [<span className="badge badge--muted">합쳐짐 → chat/was</span>, '안 쓰는 폴더(흐린 줄)'],
    ],
  },
]

export default function ConfigRepo() {
  const [rows, setRows] = useState<ConfigRow[] | null>(null)
  const [err, setErr] = useState(false)
  const [groupSel, setGroupSel] = useState('')
  const [openRows, setOpenRows] = useState<Set<string>>(new Set()) // ▸ 펼친 줄(환경별 자세히)
  const toggleRow = (path: string) =>
    setOpenRows((cur) => {
      const next = new Set(cur)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })

  const [shapes, setShapes] = useState<ShapeRow[] | null>(null) // repo 보기 + GitHub 서비스 안내
  const [side, setSideState] = useState<Side>(readSide)
  const setSide = (v: Side) => {
    setSideState(v)
    try {
      localStorage.setItem(SIDE_KEY, v)
    } catch {
      /* 저장 못 해도 화면은 그대로 */
    }
  }

  const load = () =>
    Promise.all([
      fetchConfig()
        .then((d) => {
          setRows(Array.isArray(d) ? d : [])
          setErr(false)
        })
        .catch(() => setErr(true)),
      fetchShapes()
        .then((d) => setShapes(Array.isArray(d) ? d : []))
        .catch(() => setShapes([])),
    ])

  useEffect(() => {
    load()
  }, [])

  const all = rows ?? []
  const active = all.filter((r) => !r.merged_into) // 합쳐져 안 쓰는 폴더는 비교·요약에서 뺀다
  const newestRuntime = newestBy(active, runtimeOf)
  const newestBase = newestBy(active, baseOf)
  // 요약 숫자는 폴더 기준 — 역할로 나뉜 줄(manager·syncer)은 같은 폴더라 한 번만 셈
  const folders = [...new Map(active.map((r) => [r.folder ?? r.path, r])).values()]
  const count = (s: ConfigRow['state']) => folders.filter((r) => r.state === s).length
  const oldCount = folders.reduce(
    (n, r) => n + (isOld(runtimeOf(r), newestRuntime) ? 1 : 0) + (isOld(baseOf(r), newestBase) ? 1 : 0),
    0,
  )
  // repo 보기 — GitHub 서비스는 GitLab repo 가 없어 빼고, repo 를 안 적은 서비스는 표 아래 안내
  const allShapes = shapes ?? []
  const ghServices = allShapes.filter((r) => r.host === 'github').map((r) => r.service)
  const repoRows = allShapes.filter((r) => r.host !== 'github' && r.repo)
  const noRepo = allShapes.filter((r) => r.host !== 'github' && !r.repo).map((r) => r.service)
  const repoGroups = [...new Set(repoRows.map((r) => r.group || '기타'))].sort()
  const repoShown = repoRows.filter((r) => !groupSel || (r.group || '기타') === groupSel)
  const checkCount = (label: string) => repoRows.filter((r) => repoChecks(r).some(([l]) => l === label)).length
  // 그룹(프로젝트 묶음) → 서비스 → 타입 으로 묶기 (빌드·배포 표와 같은 모양): 'admin/web' → admin 의 web
  const groupOf = (r: ConfigRow) => r.group || '기타'
  const groupNames = [...new Set(all.map(groupOf))].sort()
  const byGroup = new Map<string, Map<string, ConfigRow[]>>()
  for (const r of all.filter((x) => !groupSel || groupOf(x) === groupSel)) {
    const svcMap = byGroup.get(groupOf(r)) ?? new Map<string, ConfigRow[]>()
    const svc = r.path.split('/')[0]
    svcMap.set(svc, [...(svcMap.get(svc) ?? []), r])
    byGroup.set(groupOf(r), svcMap)
  }
  const ordered = [...byGroup.entries()]
    .sort(([a], [b]) => (a === '기타' ? 1 : b === '기타' ? -1 : a.localeCompare(b)))
    .map(([group, m]) => ({ group, svcs: [...m.entries()].sort(([a], [b]) => a.localeCompare(b)) }))
  // (서버) 열: dev·stg·prod 는 항상, lab·preview 처럼 가끔 있는 환경은 '기타' 한 열에 모음
  const envs = ['dev', 'stg', 'prod']
  const extras = ENV_ORDER.filter((e) => !envs.includes(e) && all.some((r) => r.compose?.[e] || r.compose_miss?.[e]))

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">config</h1>
        <p className="page-sub">
          {side === 'repo' ? 'repo 가 무엇으로 빌드하나 — 서비스마다' : '이미지가 무엇으로 만들어지고 어떻게 뜨나 — config repo 폴더마다'}
        </p>
      </div>

      <div className="seg" role="tablist" aria-label="config 보기" style={{ marginBottom: 12 }}>
        <span className="seg-label">보기</span>
        {SIDES.map(([v, label]) => (
          <button
            key={v}
            type="button"
            role="tab"
            aria-selected={side === v}
            className={'seg-btn' + (side === v ? ' seg-btn--active' : '')}
            onClick={() => {
              setSide(v)
              setGroupSel('')
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {side === 'repo' ? (
        <>
          <SectionHead
            title="repo 프로젝트"
            sub={shapes ? `확인할 것 — 빌드≠코드 ${checkCount('빌드≠코드')} · 빌드≠실행 ${checkCount('빌드≠실행')} · 코드≠실행 ${checkCount('코드≠실행')}` : undefined}
            right={<CollectButton asOf={latestTime(repoRows.map((r) => r.collected_at))} onDone={() => load()} />}
          />
          <RepoLegend />
          <div className="toolbar" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
            <GroupFilter groups={repoGroups} value={groupSel} onChange={setGroupSel} />
          </div>
          <div className="card" style={{ overflowX: 'auto' }}>
            <RepoTable rows={repoShown} />
            {!shapes && <div className="placeholder" style={{ padding: '28px 16px' }}>불러오는 중…</div>}
            {shapes && repoRows.length === 0 && (
              <div className="placeholder" style={{ padding: '28px 16px' }}>
                아직 repo 를 읽지 않았습니다 — <span className="mono">shape-targets.yml</span> 서비스에{' '}
                <span className="mono">repo:</span> 프로젝트를 적고 <span className="mono">python -m runner.cli shape</span>
              </div>
            )}
          </div>
          {noRepo.length > 0 && (
            <p className="note-line">repo 프로젝트를 안 적은 서비스 — {noRepo.join(', ')} (대상 파일에 repo: 를 적으면 여기 나와요)</p>
          )}
          {ghServices.length > 0 && (
            <p className="note-line">
              <span className="host-badge host-badge--github" style={{ marginLeft: 0 }}>
                GitHub
              </span>{' '}
              에서 빌드하는 서비스는 GitLab repo 가 없어 이 표에 없어요 — {ghServices.join(', ')} (빌드·배포 탭에서 봐요)
            </p>
          )}
        </>
      ) : (
        <>
          <SectionHead
            title="config 폴더"
            sub={
              rows
                ? `할 일 — CMD 로 옮기기 ${count('legacy')} · start.sh 지우기 ${count('leftover')} · CMD 넣기 ${count('server')} · 오래된 버전 ${oldCount}칸`
                : undefined
            }
            right={<CollectButton asOf={latestTime(all.map((r) => r.collected_at))} onDone={() => load()} />}
          />

          <Legend
            id="config"
            rows={LEGEND}
            source="center config repo · 서버 docker-compose — runner shape"
          />

          <div className="toolbar" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
            <GroupFilter groups={groupNames} value={groupSel} onChange={setGroupSel} />
          </div>

          <div className="card" style={{ overflowX: 'auto' }}>
            <table className="grid grid--nowrap grid--dense">
              <thead>
                <tr className="th-band">
                  <th rowSpan={3}>그룹</th>
                  <th rowSpan={3}>서비스</th>
                  <th rowSpan={3}>타입</th>
                  <th colSpan={2} className="th-group">버전</th>
                  <th colSpan={2 + envs.length + (extras.length ? 1 : 0)} className="th-group th-start">
                    start.sh — 앱을 처음 띄우는 명령은 어디에?
                    <span className="th-flow">config 의 Dockerfile → 이미지 → 서버의 docker-compose (덮어쓸 수 있음)</span>
                  </th>
                </tr>
                <tr>
                  <th rowSpan={2}>런타임 (이미지)</th>
                  <th rowSpan={2}>베이스 이미지</th>
                  <th rowSpan={2}>
                    처음 실행할 명령 (이미지)
                    <span className="th-flow">config 의 Dockerfile</span>
                  </th>
                  <th colSpan={envs.length + (extras.length ? 1 : 0)} className="th-group">
                    처음 실행할 명령 (서버)
                    <span className="th-flow">서버의 docker-compose</span>
                  </th>
                  <th rowSpan={2}>정리할 것</th>
                </tr>
                <tr>
                  {envs.map((e) => (
                    <th key={e} className="th-sub">{e}</th>
                  ))}
                  {extras.length > 0 && (
                    <th className="th-sub" title={`그 밖의 환경: ${extras.join(', ')}`}>
                      기타
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {ordered.map((g) => {
                  // 펼친 줄은 표 아래 한 줄이 더 생겨서 그룹·서비스 칸이 그만큼 더 길어짐
                  const span = (rs: ConfigRow[]) => rs.length + rs.filter((r) => openRows.has(r.path)).length
                  const total = g.svcs.reduce((n, [, rs]) => n + span(rs), 0)
                  return g.svcs.map(([svc, rs], si) => (
                    <Fragment key={`${g.group}/${svc}`}>
                      {rs.map((r, i) => {
                        const rt = runtimeOf(r)
                        const base = baseOf(r)
                        const groupFirst = si === 0 && i === 0
                        // 경계: 그룹이 바뀌면 진한 선, 서비스가 바뀌면 보통 선
                        const cls = [groupFirst ? 'grp-start' : i === 0 ? 'svc-start' : '', r.merged_into ? 'row-merged' : ''].join(' ').trim()
                        const isOpen = openRows.has(r.path)
                        return (
                          <Fragment key={r.path}>
                            <tr className={cls || undefined}>
                              {groupFirst && (
                                <td className="grp-cell" rowSpan={total}>
                                  {g.group}
                                  <div className="muted" style={{ fontWeight: 400, fontSize: 12 }}>
                                    서비스 {g.svcs.length}개
                                  </div>
                                  {/* 어느 config repo 에서 왔나 — 여기 줄은 전부 GitLab config repo */}
                                  {[...new Set(g.svcs.flatMap(([, rs]) => rs.flatMap((r) => (r.config_repo ? [r.config_repo] : []))))].map((repo) => (
                                    <div key={repo} className="muted grp-repo" title={`config repo: ${repo} (GitLab)`}>
                                      {/* '/' 에서만 줄바꿈 — 그룹 칸이 넓어지지 않게 */}
                                      {repo.split('/').map((part, i, arr) => (
                                        <span key={i} className="grp-repo-part">
                                          {part}
                                          {i < arr.length - 1 ? '/' : ''}
                                        </span>
                                      ))}
                                      <div>
                                        <span className="host-badge host-badge--gitlab">GitLab</span>
                                      </div>
                                    </div>
                                  ))}
                                </td>
                              )}
                              {i === 0 && (
                                <td className="svc-cell" rowSpan={span(rs)}>
                                  {svc}
                                </td>
                              )}
                              <td>
                                <button
                                  type="button"
                                  className="row-toggle"
                                  aria-expanded={isOpen}
                                  aria-label={`${r.path} 환경별 자세히`}
                                  title="환경별 자세히 — 어디서 읽었나 · 위치 · 못 읽은 이유"
                                  onClick={() => toggleRow(r.path)}
                                >
                                  {isOpen ? '▾' : '▸'}
                                </button>
                                {typeCell(r)}
                              </td>
                              <td>
                                {r.runtime ? (
                                  <Ver
                                    text={`${r.runtime}${r.runtime_version ? ` ${r.runtime_version}` : ''}`}
                                    old={!r.merged_into && isOld(rt, newestRuntime)}
                                    newest={rt ? `${rt[0]} ${newestRuntime.get(rt[0])}` : undefined}
                                  />
                                ) : (
                                  <span className="muted">—</span>
                                )}
                              </td>
                              <td>
                                {r.base_image ? (
                                  // 앞의 저장소 경로(infra/ 등)는 줄여서 한 줄에 — 전체 이름은 마우스
                                  <span title={`${r.base_image}${r.base_tag ? `:${r.base_tag}` : ''}`}>
                                    <Ver
                                      text={`${r.base_image.split('/').pop()}${r.base_tag ? `:${r.base_tag}` : ''}`}
                                      old={!r.merged_into && isOld(base, newestBase)}
                                      newest={base ? `${base[0]}:${newestBase.get(base[0])}` : undefined}
                                    />
                                  </span>
                                ) : (
                                  <span className="muted">—</span>
                                )}
                              </td>
                              <td>{imageCell(r, envs)}</td>
                              {envs.map((e) => (
                                <td key={e}>{serverEnvCell(r, e)}</td>
                              ))}
                              {extras.length > 0 && <td className="extras-cell">{extraCell(r, extras)}</td>}
                              <td>{todoCell(r)}</td>
                            </tr>
                            {isOpen && (
                              <tr className="row-detail">
                                <td colSpan={8 + (extras.length ? 1 : 0)}>
                                  {envDetail(r, [...envs, ...extras.filter((e) => r.compose?.[e] || r.compose_miss?.[e])])}
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        )
                      })}
                    </Fragment>
                  ))
                })}
              </tbody>
            </table>

            {!rows && !err && <div className="placeholder" style={{ padding: '28px 16px' }}>불러오는 중…</div>}
            {rows && rows.length === 0 && (
              <div className="placeholder" style={{ padding: '28px 16px' }}>
                아직 config 를 읽지 않았습니다 — <span className="mono">shape-targets.yml</span> 에{' '}
                <span className="mono">config:</span> 를 적고 <span className="mono">python -m runner.cli shape</span>
              </div>
            )}
            {err && (
              <div className="placeholder" style={{ padding: '28px 16px' }}>
                config 를 불러오지 못했습니다 — 중앙 API 상태를 확인하세요.
              </div>
            )}
          </div>
          {ghServices.length > 0 && (
            <p className="note-line">
              <span className="host-badge host-badge--github" style={{ marginLeft: 0 }}>
                GitHub
              </span>{' '}
              에서 빌드하는 서비스는 GitLab config repo 를 안 써서 이 표에 없어요 — {ghServices.join(', ')} (빌드·배포 탭에서 봐요)
            </p>
          )}
        </>
      )}
    </div>
  )
}
