import { Fragment, useEffect, useState } from 'react'
import { fetchConfig, type ComposeSrc, type ConfigRow } from '../api'
import SectionHead, { latestTime, runAll } from '../components/SectionHead'
import { isOld, newestBy, Ver, verParts } from '../vercmp'

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
  if (r.runtime === 'java' && c.java && verParts(c.java)[0] !== img) return `코드는 java ${c.java}(pom.xml), 이미지는 java ${r.runtime_version}`
  return null
}

function codeCell(r: ConfigRow) {
  const c = r.code
  if (!c || (!c.node && !c.java)) return <span className="muted" title="이 폴더와 연결된 repo 가 없거나, 버전을 적어 둔 파일이 없음">—</span>
  const main = c.node ? `node ${c.node_rule === 'min' ? '≥' : ''}${c.node}` : `java ${c.java}`
  const bad = codeMismatch(r)
  return (
    <span title={`출처: ${c.node ? c.node_from : 'pom.xml'}${c.nest ? ` · nest ${c.nest}` : ''}`}>
      <span className="ver">{main}</span>
      {bad && (
        <span className="badge badge--warn cell-badge" title={bad}>
          ⚠ 다름
        </span>
      )}
    </span>
  )
}

// 서버 compose 를 어디서 읽었나 — 칸 옆 작은 글씨. 서버 = 실서버에서 직접(SSH), 사본 = 복사해 둔 파일(다를 수 있음)
function srcLabel(info?: ComposeSrc | null): { text: string; title: string } | null {
  if (!info) return null
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

// '기타' 칸 — lab·preview 같은 환경을 한 줄에 이어서 짧게(자세한 건 마우스)
function extraCell(r: ConfigRow, extras: string[]) {
  const lines = r.start === 'base' ? extras.filter((e) => r.compose?.[e]) : extras.filter((e) => r.compose?.[e] || r.compose_miss?.[e])
  if (lines.length === 0) return <span className="muted">—</span>
  return lines.map((e, i) => {
    const c = r.compose?.[e]
    const m = r.compose_miss?.[e]
    const text = c ? (c === 'image' ? '← 이미지' : `● ${RUN[serverRun(r, e)!].label}`) : m?.state === 'fail' ? '못 읽음' : '안 읽음'
    const src = srcLabel(r.compose_src?.[e])
    const title = c ? `${e}: ${text}${src ? ` · 출처: ${src.title}` : ''}` : `${e}: ${m?.reason ?? ''}`
    return (
      <Fragment key={e}>
        {i > 0 && <span className="muted"> · </span>}
        <span className={`extra-line ${c ? (c === 'image' ? 'st-asis' : '') : m?.state === 'fail' ? 'miss-fail' : 'st-unread-text'}`} title={title}>
          <span className="muted">{e}</span> {text}
        </span>
      </Fragment>
    )
  })
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

// 타입 칸 — 폴더 이름. 이미지 하나를 역할별로 나눠 띄우면(예: manager·syncer) 옆에 작게
function typeCell(r: ConfigRow) {
  const folder = r.path.split('/')[1]
  if (!folder) return <span className="muted">—</span>
  if (!r.used_as?.length) return folder
  return (
    <span title={`config 폴더 이름은 ${folder} — 이 이미지 하나를 ${r.used_as.join('·')} 가 같이 써요(서버 compose 의 command: 로 역할을 나눠 띄움)`}>
      {folder}
      <span className="cell-tag"> → {r.used_as.join('·')}</span>
    </span>
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

export default function ConfigRepo() {
  const [rows, setRows] = useState<ConfigRow[] | null>(null)
  const [err, setErr] = useState(false)
  const [busy, setBusy] = useState(false)
  const [runtime, setRuntime] = useState('')

  const load = () =>
    fetchConfig()
      .then((d) => {
        setRows(Array.isArray(d) ? d : [])
        setErr(false)
      })
      .catch(() => setErr(true))

  useEffect(() => {
    load()
  }, [])

  const all = rows ?? []
  const active = all.filter((r) => !r.merged_into) // 합쳐져 안 쓰는 폴더는 비교·요약에서 뺀다
  const newestRuntime = newestBy(active, runtimeOf)
  const newestBase = newestBy(active, baseOf)
  const count = (s: ConfigRow['state']) => active.filter((r) => r.state === s).length
  const runtimeLabel = (r: ConfigRow) => (r.runtime ? `${r.runtime}${r.runtime_version ? ` ${r.runtime_version}` : ''}` : '')
  const runtimes = [...new Set(all.map(runtimeLabel).filter(Boolean))].sort()
  const oldCount = active.reduce(
    (n, r) => n + (isOld(runtimeOf(r), newestRuntime) ? 1 : 0) + (isOld(baseOf(r), newestBase) ? 1 : 0),
    0,
  )
  const latest = [...newestRuntime].map(([k, v]) => `${k} ${v}`).join(' · ')
  const codeDiff = active.filter((r) => codeMismatch(r)).length
  // 서비스별로 묶기: 'admin/web' → admin 의 web
  const bySvc = new Map<string, ConfigRow[]>()
  for (const r of runtime ? all.filter((x) => runtimeLabel(x) === runtime) : all) {
    const svc = r.path.split('/')[0]
    bySvc.set(svc, [...(bySvc.get(svc) ?? []), r])
  }
  const svcs = [...bySvc.entries()].sort(([a], [b]) => a.localeCompare(b))
  // (서버) 열: dev·stg·prod 는 항상, lab·preview 처럼 가끔 있는 환경은 '기타' 한 열에 모음
  const envs = ['dev', 'stg', 'prod']
  const extras = ENV_ORDER.filter((e) => !envs.includes(e) && all.some((r) => r.compose?.[e] || r.compose_miss?.[e]))

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">config</h1>
        <p className="page-sub">
          center 가 이미지를 만들 때 참조하는 config repo — 폴더(서비스/타입)마다 버전 · 처음 실행할 명령 · 정리할 것
        </p>
      </div>

      <SectionHead
        title="config 폴더"
        sub={
          rows
            ? `CMD 로 옮기기 ${count('legacy')} · 파일 지우기 ${count('leftover')} · CMD 넣기 ${count('server')} · 코드↔이미지 다름 ${codeDiff} · 오래된 버전 ${oldCount}칸${latest ? ` · 최신: ${latest}` : ''}`
            : undefined
        }
        asOf={latestTime(all.map((r) => r.collected_at))}
        onRefresh={() => runAll(setBusy, [load])}
        busy={busy}
        source="center config repo(Dockerfile·start.sh) · repo 코드(.nvmrc·package.json·pom.xml) · 서버 docker-compose · 수집 python -m runner.cli shape · 대상 shape-targets.yml"
      />

      <details className="legend" open>
        <summary>표 읽는 법</summary>
        <ul>
          <li>
            <b>처음 실행할 명령</b> = 컨테이너가 켜질 때 앱을 띄우는 명령이 어디 있나. 모든 칸이 이 말만 써요 —{' '}
            <span className="badge badge--warn">start.sh</span> 별도 스크립트 · <span className="badge badge--ok">Dockerfile CMD</span> 이미지 안 ·{' '}
            <span className="badge badge--ok">서버 compose</span> 서버의 <span className="mono">command:</span> ·{' '}
            <span className="badge badge--muted">베이스 이미지</span> springboot 처럼 이미지가 알아서(jar 실행, start.sh 안 씀) ·{' '}
            <span className="badge badge--warn">없음 → 서버가 줌</span> 이미지 혼자 못 띄움
          </li>
          <li>
            <b>(서버) 칸 모양 4가지</b> — <span className="run-dot" />
            <span className="badge badge--ok">서버 compose</span> 서버가 덮어씀 · <span className="st-asis">← 이미지</span> 확인됨(이미지 명령 그대로) ·{' '}
            <span className="st-unread">안 읽음</span> 아직 안 봄 · <span className="miss-fail st-fail">못 읽음</span> 읽으려다 실패(옆에 짧은 이유) ·{' '}
            <span className="muted">—</span> 읽을 게 없음(그 환경엔 배포 안 함, 또는 start.sh 를 안 쓰는 이미지)
          </li>
          <li>
            <span className="run-dot" /> = 그 서버에서 <b>실제로 실행되는</b> 명령. 기본은 이미지 안의 명령(Dockerfile)이 실행되고, 서버 compose 가 <span className="mono">command:</span> 를 주거나
            start.sh 를 넣으면 그게 <b>덮어써서</b> 실행돼요. <b>← 이미지</b> = 그 서버는 (이미지) 칸 명령을 그대로 씀
          </li>
          <li>
            <b>(서버) 칸 옆 작은 글씨 = 어디서 읽었나</b> — <b>서버</b>: 실서버에서 직접 읽음 · <b>자동</b>: center CI 의 배포 서버·폴더로 찾아서 읽음 · <b>gw</b>: 게이트웨이를 거쳐 실서버에서 읽음 ·{' '}
            <b>사본</b>: 복사해 둔 파일(실서버와 다를 수 있음) · <b>옛 사본</b>: 옛날 하네스 파일. 자세한 건 칸에 마우스
          </li>
          <li>
            <b>(이미지)</b> = Dockerfile 이 이미지에 넣어 둔 명령 (<span className="run-unused"><span className="badge badge--warn">흐린 배지</span></span> = 읽은 서버가 모두 덮어써서 안 쓰임) · <b>(서버) dev·stg·prod</b> = 그 서버에서 실제로 앱을 띄우는 명령 (서버 compose 가 명령을 주거나
            start.sh 를 넣으면 그게 우선, 아니면 이미지 그대로) — 파일 복사로 배포하는 서버는 이미지를 안 써서 둘이 달라질 수 있어요
          </li>
          <li>
            <b>정리할 것</b> — <span className="badge badge--danger">CMD 로 옮기기</span> start.sh 를 Dockerfile CMD 로 ·{' '}
            <span className="badge badge--warn">start.sh 지우기</span> 안 쓰는 파일 · <span className="badge badge--warn">CMD 넣기</span> 지금은 서버가 띄움 ·{' '}
            <span className="badge badge--ok">없음</span> · <span className="badge badge--muted">java 라 start.sh 안 씀</span> 베이스 이미지가 jar 를 띄움
          </li>
          <li>
            흐린 줄 + <span className="badge badge--muted">합쳐짐 → chat/was</span> = 다른 폴더로 합쳐져 안 쓰는 폴더(요약 숫자에서 빠짐)
          </li>
          <li>
            <b>코드에 적힌 버전</b> = repo 코드의 <span className="mono">.nvmrc</span>·<span className="mono">package.json</span>·<span className="mono">pom.xml</span> 에 "이 버전으로
            빌드해라" 고 적힌 값 (<b>≥20</b> = 20 이상이면 됨). 옆의 런타임(이미지)과 다르면 <span className="badge badge--warn">⚠ 다름</span>
          </li>
          <li>
            <span className="ver ver--old">⚠ 빨간 칸</span> = 같은 종류 중 최신이 아닌 버전
          </li>
        </ul>
      </details>

      <div className="toolbar" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
        <select className="search" style={{ minWidth: 140 }} value={runtime} onChange={(e) => setRuntime(e.target.value)} aria-label="런타임 필터">
          <option value="">런타임: 전체</option>
          {runtimes.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
      </div>

      <div className="card" style={{ overflowX: 'auto' }}>
        <table className="grid grid--nowrap grid--dense">
          <thead>
            <tr className="th-band">
              <th rowSpan={3}>서비스</th>
              <th rowSpan={3}>타입</th>
              <th colSpan={3} className="th-group">버전</th>
              <th colSpan={2 + envs.length + (extras.length ? 1 : 0)} className="th-group th-start">
                start.sh — 앱을 처음 띄우는 명령은 어디에?
                <span className="th-flow">config 의 Dockerfile → 이미지 → 서버의 docker-compose (덮어쓸 수 있음)</span>
              </th>
            </tr>
            <tr>
              <th rowSpan={2}>코드에 적힌 버전</th>
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
            {svcs.map(([svc, rs]) => (
              <Fragment key={svc}>
                {rs.map((r, i) => {
                  const rt = runtimeOf(r)
                  const base = baseOf(r)
                  return (
                    <tr key={r.path} className={[i === 0 ? 'svc-start' : '', r.merged_into ? 'row-merged' : ''].join(' ').trim() || undefined}>
                      {i === 0 && (
                        <td className="svc-cell" rowSpan={rs.length}>
                          {svc}
                        </td>
                      )}
                      <td>{typeCell(r)}</td>
                      <td>{codeCell(r)}</td>
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
                  )
                })}
              </Fragment>
            ))}
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
    </div>
  )
}
