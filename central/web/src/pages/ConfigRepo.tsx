import { Fragment, useEffect, useState } from 'react'
import { fetchConfig, type ConfigRow } from '../api'
import SectionHead, { latestTime, runAll } from '../components/SectionHead'
import { isOld, newestBy, Ver, verParts } from '../vercmp'

// 처음 실행할 명령 = 컨테이너가 켜질 때 앱을 띄우는 명령이 어디 있나. 모든 칸이 이 말 하나만 쓴다.
type Run = 'start.sh' | 'cmd' | 'compose' | 'base' | 'server'
const RUN: Record<Run, { label: string; tone: string; title: string }> = {
  'start.sh': { label: 'start.sh', tone: 'warn', title: 'start.sh 스크립트가 앱을 띄움' },
  cmd: { label: 'Dockerfile CMD', tone: 'ok', title: 'Dockerfile 안의 CMD 가 앱을 띄움 — start.sh 필요 없음' },
  compose: { label: '서버 compose', tone: 'ok', title: '서버 docker-compose 의 command: 가 앱을 띄움 — start.sh 필요 없음' },
  base: { label: '베이스 기본값', tone: 'muted', title: '베이스 이미지가 알아서 띄움(예: springboot)' },
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
  legacy: { label: 'start.sh → CMD 로 옮기기', tone: 'danger', title: '지금은 start.sh 가 앱을 띄움 — Dockerfile 에 CMD 를 넣고 start.sh 를 없애면 끝' },
  leftover: { label: 'start.sh 파일 지우기', tone: 'warn', title: '이미 Dockerfile CMD 가 앱을 띄움 — 폴더에 남은 start.sh 는 안 쓰임' },
  server: { label: 'Dockerfile 에 CMD 넣기', tone: 'warn', title: '지금은 서버 compose 가 명령을 줌 — 이미지 혼자 뜨도록 CMD 를 넣으면 깔끔' },
  done: { label: '없음', tone: 'ok', title: 'Dockerfile CMD 로 뜨고 start.sh 도 없음' },
  base: { label: '—', tone: 'muted', title: '베이스 이미지가 알아서 띄움 — 할 일 없음' },
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
    <span title={`출처: ${c.node ? c.node_from : 'pom.xml'}`}>
      <span className="ver">{main}</span>
      {bad && (
        <span className="badge badge--warn" style={{ display: 'table', marginTop: 2 }} title={bad}>
          ⚠ 이미지와 다름
        </span>
      )}
      {c.nest && <span className="cell-sub">nest {c.nest}</span>}
    </span>
  )
}

// (서버) 환경 한 칸 — 그 환경 compose 를 아직 못 읽었으면 —
function serverEnvCell(r: ConfigRow, env: string) {
  if (!r.compose?.[env]) return <span className="muted" title={`${env} 서버 compose 를 아직 안 읽음 — 대상 파일에 적으면 표시`}>—</span>
  return runBadge(serverRun(r, env))
}

function todoCell(r: ConfigRow) {
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
  const newestRuntime = newestBy(all, runtimeOf)
  const newestBase = newestBy(all, baseOf)
  const count = (s: ConfigRow['state']) => all.filter((r) => r.state === s).length
  const runtimeLabel = (r: ConfigRow) => (r.runtime ? `${r.runtime}${r.runtime_version ? ` ${r.runtime_version}` : ''}` : '')
  const runtimes = [...new Set(all.map(runtimeLabel).filter(Boolean))].sort()
  const oldCount = all.reduce(
    (n, r) => n + (isOld(runtimeOf(r), newestRuntime) ? 1 : 0) + (isOld(baseOf(r), newestBase) ? 1 : 0),
    0,
  )
  const latest = [...newestRuntime].map(([k, v]) => `${k} ${v}`).join(' · ')
  const codeDiff = all.filter((r) => codeMismatch(r)).length
  // 서비스별로 묶기: 'admin/web' → admin 의 web
  const bySvc = new Map<string, ConfigRow[]>()
  for (const r of runtime ? all.filter((x) => runtimeLabel(x) === runtime) : all) {
    const svc = r.path.split('/')[0]
    bySvc.set(svc, [...(bySvc.get(svc) ?? []), r])
  }
  const svcs = [...bySvc.entries()].sort(([a], [b]) => a.localeCompare(b))
  // (서버) 열: 데이터에 있는 환경만, 없으면 dev·stg·prod 기본
  const seen = ENV_ORDER.filter((e) => all.some((r) => r.compose?.[e]))
  const envs = seen.length ? seen : ['dev', 'stg', 'prod']

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
            <span className="badge badge--muted">베이스 기본값</span> springboot 처럼 이미지가 알아서 ·{' '}
            <span className="badge badge--warn">없음 → 서버가 줌</span> 이미지 혼자 못 띄움
          </li>
          <li>
            <b>(이미지)</b> = Dockerfile 이 이미지에 넣어 둔 명령 · <b>(서버) dev·stg·prod</b> = 그 서버에서 실제로 앱을 띄우는 명령 (서버 compose 가 명령을 주거나
            start.sh 를 넣으면 그게 우선, 아니면 이미지 그대로) — 파일 복사로 배포하는 서버는 이미지를 안 써서 둘이 달라질 수 있어요
          </li>
          <li>
            <b>정리할 것</b> — <span className="badge badge--danger">start.sh → CMD 로 옮기기</span> ·{' '}
            <span className="badge badge--warn">start.sh 파일 지우기</span> 안 쓰는 파일 · <span className="badge badge--warn">Dockerfile 에 CMD 넣기</span> 지금은 서버가 띄움 ·{' '}
            <span className="badge badge--ok">없음</span>
          </li>
          <li>
            <b>코드에 적힌 버전</b> = repo 코드의 <span className="mono">.nvmrc</span>·<span className="mono">package.json</span>·<span className="mono">pom.xml</span> 에 "이 버전으로
            빌드해라" 고 적힌 값 (<b>≥20</b> = 20 이상이면 됨). 옆의 런타임(이미지)과 다르면 <span className="badge badge--warn">⚠ 이미지와 다름</span>
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
            <tr>
              <th rowSpan={2}>서비스</th>
              <th rowSpan={2}>타입</th>
              <th rowSpan={2}>코드에 적힌 버전</th>
              <th rowSpan={2}>런타임 (이미지)</th>
              <th rowSpan={2}>베이스 이미지</th>
              <th rowSpan={2}>처음 실행할 명령 (이미지)</th>
              <th colSpan={envs.length} className="th-group">처음 실행할 명령 (서버)</th>
              <th rowSpan={2}>정리할 것</th>
            </tr>
            <tr>
              {envs.map((e) => (
                <th key={e} className="th-sub">{e}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {svcs.map(([svc, rs]) => (
              <Fragment key={svc}>
                {rs.map((r, i) => {
                  const rt = runtimeOf(r)
                  const base = baseOf(r)
                  return (
                    <tr key={r.path} className={i === 0 ? 'svc-start' : undefined}>
                      {i === 0 && (
                        <td className="svc-cell" rowSpan={rs.length}>
                          {svc}
                        </td>
                      )}
                      <td>{r.path.split('/')[1] ?? <span className="muted">—</span>}</td>
                      <td>{codeCell(r)}</td>
                      <td>
                        {r.runtime ? (
                          <Ver
                            text={`${r.runtime}${r.runtime_version ? ` ${r.runtime_version}` : ''}`}
                            old={isOld(rt, newestRuntime)}
                            newest={rt ? `${rt[0]} ${newestRuntime.get(rt[0])}` : undefined}
                          />
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
                      <td>{runBadge(imageRun(r))}</td>
                      {envs.map((e) => (
                        <td key={e}>{serverEnvCell(r, e)}</td>
                      ))}
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
