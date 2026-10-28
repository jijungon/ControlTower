import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError,
  fetchInventoryEntry,
  previewInventoryEdit,
  saveInventoryEdit,
  type InventoryChange,
  type InventoryEdit,
  type InventoryEntry,
} from '../api'
import { fmtTime } from './SectionHead'

// 목록 고치기(운영자) — 금고 한 항목(<환경>/<서비스>)의 gw · 서버. CT_INVENTORY_EDIT 가 켜졌고 운영자일 때만 열린다.
//   1) 열 때 금고에서 새로 읽음(판 번호 v) → 2) 고침 → 3) [바뀐 것 보기] 금고 지금 판과 비교한 목록 → 4) [저장]
//   그 사이 idp-login 이 먼저 고쳤으면(판이 바뀜) 저장하지 않고 '다시 불러온 뒤 고쳐 주세요'.
//   저장이 됐는지 모르면 '모름' 그대로 — 됐다고도, 안 됐다고도 하지 않는다.
// users 는 손대지 않는다 — idp-login user add 가 gw 에 OS 계정도 만들어서 목록만 바꾸면 어긋난다.

type Row = { key: number; name: string; addr: string }
type Msg = { kind: 'ok' | 'warn' | 'fail'; text: string; reload?: boolean; why?: string }

export function changeText(c: InventoryChange): string {
  switch (c.kind) {
    case 'gw_host':
      return `gw 주소 ${c.from ?? '(없음)'} → ${c.to}`
    case 'gw_port':
      return `gw 포트 ${c.from} → ${c.to}`
    case 'server_add':
      return `서버 추가 ${c.name} (${c.to})`
    case 'server_remove':
      return `서버 뺌 ${c.name} (${c.from})`
    case 'server_addr':
      return `서버 주소 바뀜 ${c.name}: ${c.from} → ${c.to}`
    case 'server_rename':
      return `서버 이름 바뀜 ${c.from} → ${c.to} (${c.addr})`
  }
}

function errMsg(e: unknown, what: string): Msg {
  if (e instanceof ApiError) {
    if (e.status === 409) return { kind: 'warn', text: e.message, reload: true }
    if (e.message.startsWith('저장됐는지 모름')) return { kind: 'warn', text: e.message, reload: true }
    // 서버가 할 일과 원래 까닭을 나눠 줬으면(금고 403 거절 등) 할 일을 그대로, 까닭은 작은 줄로
    if (e.why) return { kind: 'fail', text: e.message, why: e.why }
    return { kind: 'fail', text: `${what} — ${e.message}` }
  }
  // 답을 못 받음(네트워크) — 저장이었다면 됐는지 모른다
  const m = e instanceof Error ? e.message : String(e)
  return what === '저장 못 했어요'
    ? { kind: 'warn', text: `저장됐는지 모름 — 답을 못 받았어요(${m}). 다시 불러와 확인해 주세요`, reload: true }
    : { kind: 'fail', text: `${what} — ${m}` }
}

export default function InventoryEditor({ env, service, onSaved, onClose }: { env: string; service: string; onSaved: () => void; onClose: () => void }) {
  const [entry, setEntry] = useState<InventoryEntry | null>(null)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const [gwHost, setGwHost] = useState('')
  const [gwPort, setGwPort] = useState('22')
  const [rows, setRows] = useState<Row[]>([])
  const [changes, setChanges] = useState<InventoryChange[] | null>(null) // 있으면 '확인' 단계
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<Msg | null>(null)
  const nextKey = useRef(0)

  const load = useCallback(async (): Promise<boolean> => {
    setLoadErr(null)
    setChanges(null)
    try {
      const d = await fetchInventoryEntry(env, service)
      if (!d || typeof d.version !== 'number' || !d.servers || typeof d.servers !== 'object') throw new Error('응답 모양이 이상해요')
      setEntry(d)
      setGwHost(d.gw?.host ?? '')
      setGwPort(String(d.gw?.port ?? 22))
      setRows(Object.entries(d.servers).map(([name, addr]) => ({ key: nextKey.current++, name, addr })))
      return true
    } catch (e) {
      setEntry(null) // 못 읽었으면 예전 판으로 고치게 두지 않는다
      setLoadErr(e instanceof Error ? e.message : String(e))
      return false
    }
  }, [env, service])

  useEffect(() => {
    load()
  }, [load])

  // 화면의 칸 → 보낼 몸통. 이름이 겹치면 하나가 조용히 사라지므로 막는다
  const body = (): InventoryEdit | string => {
    const servers: Record<string, string> = {}
    for (const r of rows) {
      const name = r.name.trim()
      const addr = r.addr.trim()
      if (!name && !addr) continue
      if (!name || !addr) return `서버 이름과 주소를 둘 다 적어 주세요 (${name || addr})`
      if (name in servers) return `서버 이름이 겹쳐요: ${name}`
      servers[name] = addr
    }
    const host = gwHost.trim()
    let gw: InventoryEdit['gw'] = null
    if (host || entry?.gw) {
      if (!host) return 'gw 주소를 비울 수는 없어요'
      const port = Number(gwPort.trim())
      if (!Number.isInteger(port) || port < 1 || port > 65535) return `gw 포트가 이상해요: ${gwPort}`
      gw = { host, port }
    }
    return { version: entry!.version, gw, servers }
  }

  const check = async () => {
    const b = body()
    if (typeof b === 'string') return setMsg({ kind: 'fail', text: b })
    setBusy(true)
    setMsg(null)
    try {
      const r = await previewInventoryEdit(env, service, b)
      if (r.changes.length === 0) setMsg({ kind: 'ok', text: '바뀐 게 없어요' })
      else setChanges(r.changes)
    } catch (e) {
      setMsg(errMsg(e, '확인 못 했어요'))
    } finally {
      setBusy(false)
    }
  }

  const save = async () => {
    const b = body()
    if (typeof b === 'string') return setMsg({ kind: 'fail', text: b })
    setBusy(true)
    setMsg(null)
    try {
      const r = await saveInventoryEdit(env, service, b)
      if (r?.saved !== true || typeof r.version !== 'number') throw new Error('응답 모양이 이상해요')
      setMsg({ kind: 'ok', text: `저장했어요 — 금고 v${r.version}` + (r.history_error ? ` (단, ${r.history_error})` : '') })
      onSaved()
      await load() // 다음 고치기는 새 판에서
    } catch (e) {
      setChanges(null)
      setMsg(errMsg(e, '저장 못 했어요'))
    } finally {
      setBusy(false)
    }
  }

  const reload = async () => {
    setMsg(null)
    if (await load()) setMsg({ kind: 'ok', text: '금고에서 다시 불러왔어요 — 지금 판에서 다시 고쳐 주세요' })
    onSaved() // 왼쪽 · 오른쪽 목록도 금고 지금 판으로
  }

  const setRow = (key: number, patch: Partial<Row>) => setRows(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const title = `${env}/${service} 고치기`

  return (
    <div className="inv-edit" role="group" aria-label={title}>
      <div className="inv-edit__head">
        <span className="inv-edit__title">{title}</span>
        {entry && <span className="mono muted">금고 v{entry.version}</span>}
        <span className="spacer" />
        <button type="button" className="btn btn--sm" onClick={onClose}>닫기</button>
      </div>

      {loadErr && (
        <div className="inv-edit__msg inv-edit__msg--fail">
          목록 모름 — {loadErr} <button type="button" className="btn btn--sm" onClick={reload}>다시 불러오기</button>
        </div>
      )}
      {!entry && !loadErr && <div className="muted">불러오는 중…</div>}

      {entry && (
        <>
          <p className="inv-edit__who muted">
            마지막 고침: {entry.updated_at ? fmtTime(entry.updated_at) : '시각 모름'} ·{' '}
            {entry.last_edit.here ? `${entry.last_edit.by} (ControlTower 에서)` : 'ControlTower 밖(gw 의 idp-login 등)'}
          </p>

          {changes === null ? (
            <>
              <div className="inv-edit__grid">
                <span className="inv-edit__label">gw</span>
                <input aria-label="gw 주소" className="inv-input mono" value={gwHost} placeholder="gw 주소" onChange={(e) => setGwHost(e.target.value)} />
                <input aria-label="gw 포트" className="inv-input inv-input--port mono" value={gwPort} onChange={(e) => setGwPort(e.target.value)} />
                <span />
                {rows.map((r, i) => (
                  <div key={r.key} className="inv-edit__row">
                    <span className="inv-edit__label">{i === 0 ? '서버' : ''}</span>
                    <input aria-label={`서버 이름 ${i + 1}`} className="inv-input mono" value={r.name} placeholder="이름" onChange={(e) => setRow(r.key, { name: e.target.value })} />
                    <input aria-label={`서버 주소 ${i + 1}`} className="inv-input mono" value={r.addr} placeholder="주소" onChange={(e) => setRow(r.key, { addr: e.target.value })} />
                    <button type="button" className="btn btn--sm" onClick={() => setRows(rows.filter((x) => x.key !== r.key))}>
                      빼기
                    </button>
                  </div>
                ))}
              </div>
              <button type="button" className="btn btn--sm" onClick={() => setRows([...rows, { key: nextKey.current++, name: '', addr: '' }])}>
                서버 더하기
              </button>
              <p className="inv-edit__note muted">
                사람 {entry.users_count}명은 여기서 못 고쳐요 — <span className="mono">idp-login user add</span> 가 gw 에 OS 계정도 만들어서 gw 에서만 고쳐요.
              </p>
              <div className="inv-edit__actions">
                <button type="button" className="btn btn--primary btn--sm" disabled={busy} onClick={check}>
                  바뀐 것 보기
                </button>
              </div>
            </>
          ) : (
            <div className="inv-edit__confirm">
              <div className="inv-edit__label">이렇게 바뀌어요 (금고 v{entry.version} 기준)</div>
              <ul className="inv-edit__changes" aria-label="바뀌는 것">
                {changes.map((c, i) => (
                  <li key={i} className="mono">{changeText(c)}</li>
                ))}
              </ul>
              <div className="inv-edit__actions">
                <button type="button" className="btn btn--primary btn--sm" disabled={busy} onClick={save}>
                  {busy ? '저장 중…' : '저장'}
                </button>
                <button type="button" className="btn btn--sm" disabled={busy} onClick={() => setChanges(null)}>
                  더 고치기
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {msg && (
        <div className={`inv-edit__msg inv-edit__msg--${msg.kind}`} role={msg.kind === 'ok' ? 'status' : 'alert'}>
          {msg.text}
          {msg.why && <span className="inv-edit__why">{msg.why}</span>}
          {msg.reload && (
            <button type="button" className="btn btn--sm" onClick={reload}>
              다시 불러오기
            </button>
          )}
        </div>
      )}
    </div>
  )
}
