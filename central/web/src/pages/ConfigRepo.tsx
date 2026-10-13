import { Fragment, useEffect, useState } from 'react'
import { fetchConfig, type ConfigRow } from '../api'
import SectionHead, { latestTime, runAll } from '../components/SectionHead'
import { isOld, newestBy, Ver } from '../vercmp'

// 실행 명령이 어디 적혀 있나
const START_LABEL: Record<string, string> = {
  dockerfile: 'Dockerfile (CMD)',
  'start.sh': 'start.sh',
  base: '베이스 이미지 기본값',
}

const STATE: Record<ConfigRow['state'], { label: string; tone: string; title: string }> = {
  legacy: { label: '구형', tone: 'danger', title: 'start.sh 로 실행 — Dockerfile CMD 로 바꿀 대상' },
  leftover: { label: 'start.sh 잔재', tone: 'warn', title: 'Dockerfile 이 이미 CMD 로 실행 — 남은 .sh 는 지워도 됨' },
  done: { label: '완료', tone: 'ok', title: 'Dockerfile CMD 로 실행, start.sh 없음' },
  base: { label: '해당 없음', tone: 'muted', title: '베이스 이미지 기본 실행(예: springboot)' },
  none: { label: 'Dockerfile 없음', tone: 'muted', title: '폴더에 Dockerfile 이 없음' },
}

// start.sh 형태(서버 compose 기준): 앱 실행 명령이 어디서 오나
//   shell      = compose 가 start.sh 파일을 마운트해서 그 스크립트로 실행
//   compose    = compose 의 command: 에 실행 명령을 직접 적음(start.sh 필요 없음)
//   Dockerfile = compose 에 아무것도 없음 → 이미지 안의 CMD 를 그대로 씀
const MOVE: Record<string, { label: string; tone: string; title: string }> = {
  mount: { label: 'shell', tone: 'warn', title: 'compose 가 start.sh 를 마운트해서 실행 — compose 의 command: 로 옮길 대상' },
  command: { label: 'compose', tone: 'ok', title: 'compose 의 command: 로 직접 실행 — start.sh 필요 없음' },
  image: { label: 'Dockerfile', tone: 'muted', title: 'compose 에 실행 명령이 없음 — 이미지 안의 CMD 를 그대로 씀' },
}
const ENV_ORDER = ['dev', 'lab', 'stg', 'preview', 'prod']

const runtimeOf = (r: ConfigRow): [string, string] | null =>
  r.runtime && r.runtime_version ? [r.runtime, r.runtime_version] : null
const baseOf = (r: ConfigRow): [string, string] | null => (r.base_image && r.base_tag ? [r.base_image, r.base_tag] : null)

function composeCell(c?: ConfigRow['compose']) {
  const envs = Object.keys(c ?? {}).sort((a, b) => ENV_ORDER.indexOf(a) - ENV_ORDER.indexOf(b))
  if (!c || envs.length === 0) return <span className="muted" title="서버 compose 를 대상 파일(config.compose)에 적으면 표시">—</span>
  return envs.map((e) => {
    const m = MOVE[c[e]] ?? { label: c[e], tone: 'muted', title: '' }
    return (
      <span key={e} className={`badge badge--${m.tone}`} style={{ marginRight: 4 }} title={m.title}>
        {e} {m.label}
      </span>
    )
  })
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
  // 서비스별로 묶기: 'admin/web' → admin 의 web
  const bySvc = new Map<string, ConfigRow[]>()
  for (const r of runtime ? all.filter((x) => runtimeLabel(x) === runtime) : all) {
    const svc = r.path.split('/')[0]
    bySvc.set(svc, [...(bySvc.get(svc) ?? []), r])
  }
  const svcs = [...bySvc.entries()].sort(([a], [b]) => a.localeCompare(b))

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">config</h1>
        <p className="page-sub">
          center 가 이미지를 만들 때 참조하는 config repo — 폴더(서비스/타입)마다 베이스 이미지 · 실행 명령 위치 · start.sh · start.sh 형태
        </p>
      </div>

      <SectionHead
        title="config 폴더"
        sub={
          rows
            ? `start.sh 구형 ${count('legacy')} · 잔재 ${count('leftover')} · 완료 ${count('done')} · 오래된 버전 ${oldCount}칸${latest ? ` · 최신: ${latest}` : ''}`
            : undefined
        }
        asOf={latestTime(all.map((r) => r.collected_at))}
        onRefresh={() => runAll(setBusy, [load])}
        busy={busy}
      />

      <details className="legend" open>
        <summary>표 읽는 법</summary>
        <ul>
          <li>
            <b>실행 명령 위치</b> = 컨테이너가 켜질 때 앱을 실행하는 명령이 어디 적혀 있나 — <b>Dockerfile (CMD)</b>: 이미지 안에 들어 있음(=CMD 내장,
            start.sh 필요 없음) · <b>start.sh</b>: 별도 스크립트 파일로 실행 · <b>베이스 이미지 기본값</b>: 베이스 이미지가 알아서 실행(예: springboot)
          </li>
          <li>
            <b>상태</b> — <span className="badge badge--danger">구형</span> start.sh 로 실행 ·{' '}
            <span className="badge badge--warn">start.sh 잔재</span> CMD 로 실행하는데 .sh 파일만 남음(지워도 됨) ·{' '}
            <span className="badge badge--ok">완료</span>
          </li>
          <li>
            <b>start.sh 형태</b> (서버 compose 기준, 환경별) — <span className="badge badge--warn">shell</span> compose 가 start.sh 파일을 마운트해서 실행(옮길 대상) ·{' '}
            <span className="badge badge--ok">compose</span> compose 의 <span className="mono">command:</span> 에 명령을 직접 적음(start.sh 없음) ·{' '}
            <span className="badge badge--muted">Dockerfile</span> compose 엔 없고 이미지 안의 CMD 를 그대로 씀
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
              <th>서비스</th>
              <th>타입</th>
              <th>런타임</th>
              <th>베이스 이미지</th>
              <th>실행 명령 위치</th>
              <th>start.sh 파일</th>
              <th>상태</th>
              <th>start.sh 형태 (서버)</th>
            </tr>
          </thead>
          <tbody>
            {svcs.map(([svc, rs]) => (
              <Fragment key={svc}>
                {rs.map((r, i) => {
                  const rt = runtimeOf(r)
                  const base = baseOf(r)
                  const st = STATE[r.state] ?? STATE.none
                  return (
                    <tr key={r.path} className={i === 0 ? 'svc-start' : undefined}>
                      {i === 0 && (
                        <td className="svc-cell" rowSpan={rs.length}>
                          {svc}
                        </td>
                      )}
                      <td>{r.path.split('/')[1] ?? <span className="muted">—</span>}</td>
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
                      <td>{r.start ? START_LABEL[r.start] ?? r.start : <span className="muted">—</span>}</td>
                      <td>{r.start_files?.length ? <span className="mono">{r.start_files.join(', ')}</span> : <span className="muted">없음</span>}</td>
                      <td>
                        <span className={`badge badge--${st.tone}`} title={st.title}>{st.label}</span>
                      </td>
                      <td>{composeCell(r.compose)}</td>
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
