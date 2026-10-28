import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { fetchAccess, type Access, type AccessPerson } from '../api'
import InventoryEditor from './InventoryEditor'
import PersonName from './PersonName'

// 서버 탭 '누가 · 어디로' — 사람 | 선 | 환경
//   왼쪽(사람): Gmail 마다 운영자 · 개발자 + 들어가는 계정 (운영자: gw · 서버 ubuntu / 개발자: gw 개인 계정 · 서버 appuser)
//   가운데(선): 사람이 실제로 갈 수 있는 환경까지 직각 선 — 운영자 주황 · 굵고 긴 점선 / 개발자 청록 · 가늘고 짧은 점선
//   오른쪽(곳): 환경 → gw → 서버. 칠 명령은 gw · 서버 줄을 누르면 그 아래에(처음부터 다 늘어놓지 않음)
// 목록은 금고에만 있다(idp-login 이 적는다). 기본은 **보기만** — 고치기는 gw 에서 idp-login 으로.
//   CT_INVENTORY_EDIT 가 켜졌고 운영자면(can_edit) [목록 고치기] → gw 마다 gw · 서버를 고침(사람은 못 고침). InventoryEditor
// 사람에 마우스를 올리거나 누르면 그 사람 선과 갈 수 있는 환경만 남고 나머지는 흐리게.
// 이름은 이름표(Authentik — IdP 서버가 5분마다 적음)에서: 운영자 줄은 실제 운영자들(활성 먼저 · 비활성은 흐리게),
//   개발자 줄은 이메일 옆 이름. 이름표를 모르면 운영자 줄은 'server-admin 그룹 전원' + '이름 모름' — '운영자 없음' 이 아니다.

const ROLE_LABEL: Record<AccessPerson['role'], string> = { admin: '운영자', developer: '개발자' }
const BUS = { admin: 0.35, developer: 0.65 } // 선이 세로로 지나는 자리(가운데 칸 너비의 몇 %) — 운영자 · 개발자가 안 겹치게
const END_DY = { admin: -8, developer: 8 } // 환경 제목 높이에서 살짝 나눔

// 선을 그릴 환경 — 운영자는 보이는 모든 환경, 개발자는 그 사람의 where
function reach(p: AccessPerson, envs: string[]): string[] {
  return p.role === 'admin' ? envs : envs.filter((e) => p.where.some((w) => w.env === e))
}

function canGo(p: AccessPerson | null, env: string, service: string): boolean {
  if (!p) return true
  return p.where.some((w) => w.env === env && w.service === service)
}

// 명령을 누구 계정으로 보여 줄지 — 고른 사람, 아무도 안 골랐으면 보는 사람 자신
type Who = { label: string; person: AccessPerson | null; self: boolean; missing?: boolean }

function viewerSelf(data: Access): Who {
  if (data.viewer.role === '개발자') {
    const mine = (data.viewer.email ?? '').toLowerCase()
    const me = data.people.find((p) => p.role === 'developer' && p.email.toLowerCase() === mine)
    return me ? { label: `나 (${me.email})`, person: me, self: true } : { label: '나', person: null, self: true, missing: true }
  }
  return { label: `나 (${data.viewer.role || '운영자'})`, person: null, self: true } // 운영자 · 로컬 미리보기 = ubuntu
}

function command(who: Who, env: string, service: string, server: string | null): { cmd?: string; no?: string } {
  if (who.missing) return { no: '내 계정이 금고 목록에 없어요 — gw 에서 idp-login user add 로 넣어야 들어가요' }
  const p = who.person
  if (p && !canGo(p, env, service)) return { no: who.self ? '나는 못 들어가요' : '이 사람은 못 들어가요' }
  const acct = !p || p.role === 'admin' ? 'ubuntu' : server ? p.server_account : p.gw_account
  return { cmd: `idp-login ssh ${acct} ${env} ${server ?? service}` }
}

function CmdBox({ who, env, service, server }: { who: Who; env: string; service: string; server: string | null }) {
  const [copied, setCopied] = useState<'ok' | 'fail' | null>(null)
  useEffect(() => {
    if (copied !== 'ok') return
    const t = setTimeout(() => setCopied(null), 1500)
    return () => clearTimeout(t)
  }, [copied])

  const res = command(who, env, service, server)
  if (res.no) return <div className="access-cmdbox access-cmdbox--no">{res.no}</div>
  const copy = () => {
    if (!navigator.clipboard) return setCopied('fail')
    navigator.clipboard.writeText(res.cmd!).then(
      () => setCopied('ok'),
      () => setCopied('fail'),
    )
  }
  return (
    <div className="access-cmdbox">
      <span className="access-cmdbox__who">{who.label} 기준</span>
      <code className="mono access-cmd">
        {server ? 'gw 안에서: ' : ''}
        {res.cmd}
      </code>
      <button type="button" className="btn btn--sm" onClick={copy}>
        {copied === 'ok' ? '복사됨' : '복사'}
      </button>
      {copied === 'fail' && <span className="muted">복사 못 함 — 글자를 직접 골라 주세요</span>}
    </div>
  )
}

type Pt = { x: number; y: number }
type Geo = { w: number; h: number; from: Record<string, Pt>; to: Record<string, Pt>; bus: Record<AccessPerson['role'], number> }

function AccessView({ data, onSaved }: { data: Access; onSaved: () => void }) {
  const [picked, setPicked] = useState<string | null>(null)
  const [editing, setEditing] = useState(false) // 목록 고치기 모드(운영자 · 스위치 켜짐일 때만 버튼이 보임)
  const [editTarget, setEditTarget] = useState<string | null>(null) // 고치는 항목 — 한 번에 하나
  const [hovered, setHovered] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [geo, setGeo] = useState<Geo | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const midRef = useRef<HTMLDivElement>(null)
  const personEls = useRef(new Map<string, HTMLElement>())
  const envEls = useRef(new Map<string, HTMLElement>())
  const headEls = useRef(new Map<string, HTMLElement>())

  // 선 자리 = 상자들의 실제 위치. 명령을 펼치거나 화면 폭이 바뀌어 상자가 길어지면 다시 잰다
  const measure = useCallback(() => {
    const wrap = wrapRef.current
    const mid = midRef.current
    if (!wrap || !mid) return
    const W = wrap.getBoundingClientRect()
    const M = mid.getBoundingClientRect()
    const from: Record<string, Pt> = {}
    personEls.current.forEach((el, email) => {
      const r = el.getBoundingClientRect()
      from[email] = { x: r.right - W.left, y: r.top + r.height / 2 - W.top }
    })
    const to: Record<string, Pt> = {}
    envEls.current.forEach((el, env) => {
      const r = el.getBoundingClientRect()
      const h = headEls.current.get(env)?.getBoundingClientRect() ?? r
      to[env] = { x: r.left - W.left, y: h.top + h.height / 2 - W.top }
    })
    const bx = (f: number) => M.left - W.left + M.width * f
    setGeo({ w: W.width, h: W.height, from, to, bus: { admin: bx(BUS.admin), developer: bx(BUS.developer) } })
  }, [])

  useLayoutEffect(() => {
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => measure())
    if (wrapRef.current) ro.observe(wrapRef.current)
    personEls.current.forEach((el) => ro.observe(el))
    envEls.current.forEach((el) => ro.observe(el))
    return () => ro.disconnect()
  }, [measure, data])

  const envNames = data.envs.map((e) => e.env)
  const links = data.people.flatMap((p) => reach(p, envNames).map((env) => ({ person: p, env })))
  const focus = data.people.find((p) => p.email === (hovered ?? picked)) ?? null
  const focusReach = focus ? reach(focus, envNames) : null
  const pickedPerson = data.people.find((p) => p.email === picked) ?? null
  const who: Who = pickedPerson ? { label: pickedPerson.email, person: pickedPerson, self: false } : viewerSelf(data)
  const toggle = (key: string) => setOpen(open === key ? null : key)
  const keep = (map: Map<string, HTMLElement>, key: string) => (el: HTMLElement | null) => {
    if (el) map.set(key, el)
    else map.delete(key)
  }

  return (
    <>
      {/* 선 색 범례는 뺌(10-28) — 배지 · 상자 테두리 색으로 충분 */}
      <div className="access-tools">
        <p className="access-legend muted">사람에 마우스를 올리거나 누르면 그 사람 길만 · gw · 서버 줄을 누르면 칠 명령</p>
        {data.can_edit === true && (
          <button
            type="button"
            className={'btn btn--sm' + (editing ? ' btn--primary' : '')}
            aria-pressed={editing}
            onClick={() => {
              setEditing(!editing)
              setEditTarget(null)
            }}
          >
            {editing ? '고치기 끝' : '목록 고치기'}
          </button>
        )}
      </div>
      {editing && (
        <p className="access-edit-note">
          운영자만 · gw 마다 [고치기] — gw 주소 · 포트와 서버(이름 · 주소)만 고쳐요. 사람(누가)은 못 고쳐요 —{' '}
          <span className="mono">idp-login user add</span> 가 gw 에 OS 계정도 만들어서 gw 에서만. 새 서비스도 gw 에서{' '}
          <span className="mono">idp-login service add</span>.
        </p>
      )}
      <div className="access" ref={wrapRef}>
        <aside className="card access-people" aria-label="사람">
          <div className="access-colhead">사람</div>
          {data.people.map((p) => (
            <button
              key={p.email}
              ref={keep(personEls.current, p.email)}
              type="button"
              className={`access-person access-person--${p.role}` + (picked === p.email ? ' access-person--on' : '')}
              aria-pressed={picked === p.email}
              onClick={() => setPicked(picked === p.email ? null : p.email)}
              onMouseEnter={() => setHovered(p.email)}
              onMouseLeave={() => setHovered(null)}
            >
              <span className={'badge ' + (p.role === 'admin' ? 'access-badge--admin' : 'access-badge--dev')}>{ROLE_LABEL[p.role]}</span>
              {p.role === 'admin' && p.members && p.members.length > 0 ? (
                <span className="access-members" data-testid="admin-members">
                  {p.members.map((m, i) => (
                    <span key={m.email ?? `${m.name}-${i}`} className={'access-member' + (m.active ? '' : ' access-member--inactive')}>
                      {m.name ?? m.email}
                      {!m.active && ' (비활성)'}
                      {m.name && m.email && <span className="access-member__email">{m.email}</span>}
                    </span>
                  ))}
                </span>
              ) : (
                <span className="access-person__who">
                  {p.email}
                  {p.role === 'developer' && <PersonName name={p.name} active={p.active} />}
                </span>
              )}
              {p.role === 'admin' && p.names_note && <span className="access-names-note">{p.names_note}</span>}
              <span className="access-person__acct">gw {p.gw_account}{p.role === 'developer' ? ' (개인)' : ''} · 서버 {p.server_account}</span>
              {p.note && <span className="access-person__acct">{p.note}</span>}
            </button>
          ))}
          <p className="access-foot" title={data.names?.reasons.join(' · ') || undefined}>
            {data.names?.state === 'ok'
              ? '이름은 Authentik 이름표에서 가져와요(5분마다).'
              : data.names?.state === 'unknown'
                ? `이름 모름 — ${data.names.reasons.join(' · ') || '이름표를 못 읽음'}`
                : '이름표 연결 전 — 이메일만 보여요.'}
          </p>
        </aside>

        <div className="access-mid" ref={midRef} aria-hidden="true" />

        <section className="access-places" aria-label="환경 · gw · 서버">
          {data.envs.map((e) => {
            const admins = data.people.some((p) => p.role === 'admin')
            const devs = data.people.some((p) => p.role === 'developer' && reach(p, envNames).includes(e.env))
            return (
              <div
                key={e.env}
                ref={keep(envEls.current, e.env)}
                className={'card access-env' + (focusReach && !focusReach.includes(e.env) ? ' access-env--dim' : '')}
                data-testid={`env-${e.env}`}
              >
                <div className="access-env__head" ref={keep(headEls.current, e.env)}>
                  <span className="access-env__name">{e.env}</span>
                  <span className="access-env__right">
                    <span className="muted">{e.audience}</span>
                    {admins && <span className="access-dot access-dot--admin" title="운영자가 갈 수 있음" />}
                    {devs && <span className="access-dot access-dot--dev" title="개발자가 갈 수 있음" />}
                  </span>
                </div>
                {e.services.length === 0 && <div className="muted access-empty">목록에 적힌 gw 가 없어요</div>}
                {e.services.map((s) => {
                  const gwKey = `gw:${e.env}:${s.name}`
                  const editKey = `${e.env}/${s.name}`
                  return (
                    <div key={s.name} className={'access-gw' + (canGo(focus, e.env, s.name) ? '' : ' access-gw--dim')} data-testid={`gw-${e.env}-${s.name}`}>
                      <button type="button" className="access-row" aria-expanded={open === gwKey} onClick={() => toggle(gwKey)}>
                        <span className="access-gw__name">{s.name} · gw</span>
                        <span className="mono muted">{s.gw ? `${s.gw.host}${s.gw.port !== 22 ? `:${s.gw.port}` : ''}` : '(gw 주소 없음)'}</span>
                        <span className="access-row__hint">{open === gwKey ? '명령 닫기' : '명령 보기'}</span>
                      </button>
                      {open === gwKey && <CmdBox who={who} env={e.env} service={s.name} server={null} />}
                      {s.servers.map((v) => {
                        const srvKey = `srv:${e.env}:${s.name}:${v.name}`
                        return (
                          <div key={v.name} className="access-srv">
                            <button type="button" className="access-row" aria-expanded={open === srvKey} onClick={() => toggle(srvKey)}>
                              <span>{v.name}</span>
                              <span className="mono muted">{v.addr}</span>
                              <span className="access-row__hint">{open === srvKey ? '명령 닫기' : '명령 보기'}</span>
                            </button>
                            {open === srvKey && <CmdBox who={who} env={e.env} service={s.name} server={v.name} />}
                          </div>
                        )
                      })}
                      {editing && editTarget !== editKey && (
                        <div className="access-edit-open">
                          <button type="button" className="btn btn--sm" onClick={() => setEditTarget(editKey)}>
                            {s.name} 고치기
                          </button>
                        </div>
                      )}
                      {editing && editTarget === editKey && (
                        <InventoryEditor env={e.env} service={s.name} onSaved={onSaved} onClose={() => setEditTarget(null)} />
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </section>

        {geo && (
          <svg className="access-links" width={geo.w} height={geo.h} aria-hidden="true">
            {links.map((l, i) => {
              const a = geo.from[l.person.email]
              const b = geo.to[l.env]
              if (!a || !b) return null
              const role = l.person.role
              const y2 = b.y + END_DY[role]
              const d = `M${a.x},${a.y} H${geo.bus[role]} V${y2} H${b.x}`
              const dim = focus !== null && focus.email !== l.person.email
              return (
                <g key={`${l.person.email}|${l.env}`} className={`access-link access-link--${role}` + (dim ? ' access-link--dim' : '')} data-testid={`link-${l.person.email}-${l.env}`}>
                  <path className="access-link__base" d={d} />
                  <path className="access-link__flow" d={d} style={{ animationDelay: `${-0.4 * i}s` }} />
                  <circle className="access-link__end" cx={b.x} cy={y2} r={3} />
                </g>
              )
            })}
            {data.people.map((p) => {
              const a = geo.from[p.email]
              if (!a || reach(p, envNames).length === 0) return null
              const dim = focus !== null && focus.email !== p.email
              return <circle key={p.email} className={`access-link__start access-link--${p.role}` + (dim ? ' access-link--dim' : '')} cx={a.x} cy={a.y} r={3.5} />
            })}
          </svg>
        )}
      </div>
    </>
  )
}

export default function AccessMap() {
  const [data, setData] = useState<Access | null>(null)
  const [err, setErr] = useState<string | null>(null)

  // 고친 뒤에도 다시 부른다(서버는 저장하면 목록 캐시를 비움)
  const load = useCallback(() => {
    // 모양이 다른 답(예: 옛 API · 로그인 화면)을 그대로 그리면 화면이 통째로 죽는다 — '모름' 으로
    fetchAccess().then(
      (d) => (d && typeof d.state === 'string' && Array.isArray(d.envs) && Array.isArray(d.people) ? setData(d) : setErr('응답 모양이 이상해요')),
      (e: Error) => setErr(e.message),
    )
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (err) return <div className="card placeholder access-msg">목록을 불러오지 못했어요 — {err}</div>
  if (!data) return <div className="card placeholder access-msg">불러오는 중…</div>
  if (data.state === 'off')
    return (
      <div className="card placeholder access-msg">
        금고 목록에 아직 연결하지 않았어요 (CT_INVENTORY_MODE=off). 목록은 gw 에서 <span className="mono">idp-login service add · server add</span> 로 적어요.
      </div>
    )
  if (data.state === 'no_identity')
    return (
      <div className="card placeholder access-msg access-msg--warn">
        로그인 정보(그룹)를 몰라 목록을 보여 줄 수 없어요 — 운영 목록이 아무에게나 보이지 않게 막아 두었어요. ControlTower 가 Authentik 그룹을 받도록 연결하면 보여요.
      </div>
    )
  if (data.state === 'denied')
    return <div className="card placeholder access-msg">볼 수 있는 목록이 없어요 — Authentik 그룹(server-admin · developer)을 관리자에게 물어보세요.</div>
  if (data.state === 'error')
    return <div className="card placeholder access-msg access-msg--warn">목록 모름 — 금고를 못 읽었어요: {data.error}</div>

  return <AccessView data={data} onSaved={load} />
}
