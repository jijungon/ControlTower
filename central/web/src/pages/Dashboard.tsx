import { useEffect, useState } from 'react'
import { fetchConf, fetchConfig, fetchShapes, fetchUpdates, type ConfigRow, type ConfRow, type ShapeRow, type UpdateRow } from '../api'
import { fmtTime, latestTime, RefreshButton, runAll } from '../components/SectionHead'
import { isOld, newestBy } from '../vercmp'
import { codeMismatch } from './ConfigRepo'

// 대시보드 = 탭마다 한눈 요약. 카드를 누르면 그 탭으로.
//   서버(/etc 설정 파일 — 서버 목록은 IdP 연동 후) · config(이미지·처음 실행할 명령) · 빌드·배포(CI 배포 방식) · OS 패치

// 마지막 수집 이후 경과 일수 (데이터 없으면 null). 오래됨 표시용.
function daysSince(iso: string | null): number | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return null
  return Math.floor((Date.now() - t) / 86400000)
}

const runtimeOf = (r: ConfigRow): [string, string] | null => (r.runtime && r.runtime_version ? [r.runtime, r.runtime_version] : null)
const baseOf = (r: ConfigRow): [string, string] | null => (r.base_image && r.base_tag ? [r.base_image, r.base_tag] : null)

type Stat = { tab: string; num: string; label: string; tone: 'ok' | 'warn' | 'danger'; sub?: string }

export default function Dashboard({ onGo }: { onGo?: (tab: string) => void }) {
  const [conf, setConf] = useState<ConfRow[] | null>(null)
  const [updates, setUpdates] = useState<UpdateRow[] | null>(null)
  const [shapes, setShapes] = useState<ShapeRow[]>([])
  const [config, setConfig] = useState<ConfigRow[]>([])
  const [err, setErr] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = () =>
    Promise.all([
      Promise.all([fetchConf(), fetchUpdates()])
        .then(([c, u]) => {
          setConf(c)
          setUpdates(u)
          setErr(false)
        })
        .catch(() => setErr(true)),
      fetchShapes().then((d) => setShapes(Array.isArray(d) ? d : [])).catch(() => setShapes([])),
      fetchConfig().then((d) => setConfig(Array.isArray(d) ? d : [])).catch(() => setConfig([])),
    ])

  useEffect(() => {
    load()
  }, [])

  const ready = conf !== null && updates !== null

  // ── 서버(/etc 설정 파일) · OS 패치 ──
  const drift = (conf ?? []).filter((r) => r.status === 'drift').length
  const pending = (updates ?? []).reduce((a, r) => a + r.pending, 0)
  const security = (updates ?? []).reduce((a, r) => a + r.security, 0)
  const secTop = (updates ?? []).filter((r) => r.security > 0).sort((a, b) => b.security - a.security).slice(0, 5)

  // ── 빌드·배포: 파일 복사로 배포하는 곳(이미지로 옮길 대상) · CI 와 서버 compose 가 다른 곳 · 확인 못 한 executor ──
  const cells = shapes.flatMap((r) => Object.entries(r.deploy ?? {}).map(([env, c]) => ({ svc: r.service, env, c })))
  const direct = cells.filter((x) => x.c.path === 'direct' && x.c.by !== 'compose')
  const directRepo = direct.filter((x) => (x.c.by ?? 'repo') === 'repo').length
  const mismatch = cells.filter((x) => x.c.mismatch)
  const guessed = shapes.reduce(
    (n, r) => n + [r.executor_repo, r.executor_center].reduce((m, e) => m + (e?.groups ?? []).filter((g) => g.guess).length, 0),
    0,
  )

  // ── config: 할 일(폴더 기준 한 번) · 오래된 버전 · 코드≠이미지 · 못 읽은 서버 칸 ──
  const active = config.filter((r) => !r.merged_into)
  const folders = [...new Map(active.map((r) => [r.folder ?? r.path, r])).values()]
  const nState = (s: ConfigRow['state']) => folders.filter((r) => r.state === s).length
  const [toCmd, toDel, toAdd] = [nState('legacy'), nState('leftover'), nState('server')]
  const newestRuntime = newestBy(active, runtimeOf)
  const newestBase = newestBy(active, baseOf)
  const oldCells = folders.reduce((n, r) => n + (isOld(runtimeOf(r), newestRuntime) ? 1 : 0) + (isOld(baseOf(r), newestBase) ? 1 : 0), 0)
  const codeDiff = folders.filter((r) => codeMismatch(r)).length
  const readFail = active.reduce((n, r) => n + Object.values(r.compose_miss ?? {}).filter((m) => m.state === 'fail').length, 0)
  const legacy = folders.filter((r) => r.state === 'legacy')

  const tone = (n: number, bad: 'warn' | 'danger' = 'warn') => (n > 0 ? bad : 'ok')
  const stats: Stat[] = [
    { tab: '서버', num: String(drift), label: '설정 드리프트', tone: tone(drift) },
    {
      tab: 'config', num: String(toCmd + toDel + toAdd), label: 'start.sh 할 일', tone: toCmd > 0 ? 'danger' : tone(toDel + toAdd),
      sub: `CMD 로 옮기기 ${toCmd} · 지우기 ${toDel} · CMD 넣기 ${toAdd}`,
    },
    { tab: 'config', num: String(oldCells), label: '오래된 버전', tone: tone(oldCells), sub: `코드≠이미지 ${codeDiff}` },
    {
      tab: '빌드·배포', num: String(direct.length), label: '파일 복사 배포', tone: tone(direct.length),
      sub: `이미지로 옮길 곳 · repo 직배포 ${directRepo}`,
    },
    { tab: 'OS 패치·작업이력', num: String(security), label: '보안 패치', tone: tone(security, 'danger'), sub: `대기 ${pending}` },
  ]

  // 데이터 기준: 모든 탭 수집 중 가장 최근
  const lastCollected = latestTime([
    ...(conf ?? []).map((r) => r.collected_at),
    ...(updates ?? []).map((r) => r.collected_at),
    ...shapes.map((r) => r.collected_at),
    ...config.map((r) => r.collected_at),
  ])
  const staleDays = daysSince(lastCollected)
  const when = (times: (string | null | undefined)[]) => {
    const t = latestTime(times)
    return t ? fmtTime(t) : '—'
  }
  const issue = (label: string, n: number, cls: 'warn' | 'danger' = 'warn') =>
    n > 0 ? (
      <span key={label} className={`badge badge--${cls}`} style={{ marginRight: 4 }}>
        {label} {n}
      </span>
    ) : null

  return (
    <div>
      <div className="page-head page-head--row">
        <div>
          <h1 className="page-title">대시보드</h1>
          <p className="page-sub">
            탭마다 한눈 요약 — 카드를 누르면 그 탭으로
            {ready && lastCollected && <> · 데이터 기준 {fmtTime(lastCollected)}</>}
            {ready && staleDays !== null && staleDays >= 7 && <span className="muted"> · {staleDays}일 지남</span>}
          </p>
        </div>
        <RefreshButton label="대시보드 새로고침" onClick={() => runAll(setBusy, [load])} busy={busy} />
      </div>

      {err && (
        <div className="card">
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            API 연결 실패 — <span className="mono">make dev</span> 로 중앙 API를 띄우세요.
          </div>
        </div>
      )}

      {!err && (
        <>
          <div className="stats stats--5">
            {stats.map((s) => (
              // 다른 탭으로 가는 것이라 링크(위쪽 탭 버튼과 헷갈리지 않게)
              <a
                key={s.label}
                href={`#${s.tab}`}
                className={`stat stat--${s.tone} stat--link`}
                onClick={(e) => {
                  e.preventDefault()
                  onGo?.(s.tab)
                }}
                title={`${s.tab} 탭에서 보기`}
              >
                <div className="stat-tab">{s.tab}</div>
                <div className="num">{ready ? s.num : '…'}</div>
                <div className="label">{s.label}</div>
                {s.sub && <div className="stat-sub">{s.sub}</div>}
              </a>
            ))}
          </div>

          {(legacy.length > 0 || mismatch.length > 0 || secTop.length > 0) && (
            <>
              <div className="subhead">⚠ 먼저 볼 것</div>
              <div className="card" style={{ marginBottom: 16 }}>
                <table className="grid">
                  <thead>
                    <tr>
                      <th>탭</th>
                      <th>구분</th>
                      <th>대상</th>
                      <th>내용</th>
                    </tr>
                  </thead>
                  <tbody>
                    {legacy.map((r) => (
                      <tr key={`cmd:${r.path}`}>
                        <td className="muted">config</td>
                        <td><span className="badge badge--danger">CMD 로 옮기기</span></td>
                        <td>{r.folder ?? r.path}</td>
                        <td className="muted">start.sh 가 앱을 띄움 — Dockerfile CMD 로</td>
                      </tr>
                    ))}
                    {mismatch.map((x) => (
                      <tr key={`mm:${x.svc}:${x.env}`}>
                        <td className="muted">빌드·배포</td>
                        <td><span className="badge badge--warn">⚠ compose 다름</span></td>
                        <td>{x.svc} · {x.env}</td>
                        <td className="muted">CI 와 서버 compose 의 배포 모양이 다름</td>
                      </tr>
                    ))}
                    {secTop.map((r) => (
                      <tr key={`sec:${r.server_id}`}>
                        <td className="muted">OS 패치</td>
                        <td><span className="badge badge--warn">보안 밀림</span></td>
                        <td>{r.hostname}</td>
                        <td className="mono">보안 {r.security} · 대기 {r.pending}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <div className="subhead">수집 현황</div>
          <div className="card">
            <table className="grid">
              <thead>
                <tr>
                  <th>탭</th>
                  <th>무엇</th>
                  <th>수집</th>
                  <th>이슈</th>
                  <th>최근 수집</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="muted">서버</td>
                  <td>/etc 설정 파일</td>
                  <td>{conf?.length ?? 0}건</td>
                  <td>{drift > 0 ? <span className="badge badge--warn">드리프트 {drift}</span> : <span className="badge badge--ok">동기화</span>}</td>
                  <td className="muted">{when((conf ?? []).map((r) => r.collected_at))}</td>
                </tr>
                <tr>
                  <td className="muted">config</td>
                  <td>이미지 · 처음 실행할 명령</td>
                  <td>{config.length}줄</td>
                  <td>
                    {issue('할 일', toCmd + toDel + toAdd, toCmd > 0 ? 'danger' : 'warn')}
                    {issue('오래된 버전', oldCells)}
                    {issue('못 읽음', readFail, 'danger')}
                    {toCmd + toDel + toAdd + oldCells + readFail === 0 && <span className="badge badge--ok">정리됨</span>}
                  </td>
                  <td className="muted">{when(config.map((r) => r.collected_at))}</td>
                </tr>
                <tr>
                  <td className="muted">빌드·배포</td>
                  <td>CI 배포 방식</td>
                  <td>{shapes.length}개 서비스</td>
                  <td>
                    {issue('파일 복사', direct.length)}
                    {issue('compose 다름', mismatch.length)}
                    {issue('executor 추정', guessed)}
                    {direct.length + mismatch.length + guessed === 0 && <span className="badge badge--ok">이미지 배포</span>}
                  </td>
                  <td className="muted">{when(shapes.map((r) => r.collected_at))}</td>
                </tr>
                <tr>
                  <td className="muted">OS 패치</td>
                  <td>대기 업데이트</td>
                  <td>{updates?.length ?? 0}대</td>
                  <td>
                    {security > 0 ? (
                      <span className="badge badge--danger">보안 {security}</span>
                    ) : pending > 0 ? (
                      <span className="badge badge--warn">대기 {pending}</span>
                    ) : (
                      <span className="badge badge--ok">최신</span>
                    )}
                  </td>
                  <td className="muted">{when((updates ?? []).map((r) => r.collected_at))}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
