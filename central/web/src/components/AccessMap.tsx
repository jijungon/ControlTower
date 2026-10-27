import { useEffect, useState } from 'react'
import { fetchAccess, type Access, type AccessPerson } from '../api'

// 서버 탭 '누가 · 어디로' — 2 : 8
//   왼쪽(사람): Gmail 마다 운영자 · 개발자 + 들어가는 계정 (운영자: gw · 서버 ubuntu / 개발자: gw 개인 계정 · 서버 appuser)
//   오른쪽(곳): 환경 → gw → 서버 + 칠 명령
// 목록은 금고에만 있다(idp-login 이 적는다). 이 화면은 **보기만** — 고치기는 gw 에서 idp-login 으로.
// 사람을 누르면 그 사람이 갈 수 있는 곳만 또렷하게, 나머지는 흐리게.

const ROLE_LABEL: Record<AccessPerson['role'], string> = { admin: '운영자', developer: '개발자' }

function canGo(p: AccessPerson | null, env: string, service: string): boolean {
  if (!p) return true
  return p.where.some((w) => w.env === env && w.service === service)
}

function sshFor(p: AccessPerson | null, env: string, target: string, isGw: boolean): string {
  const acct = !p || p.role === 'admin' ? 'ubuntu' : isGw ? p.gw_account : p.server_account
  return `idp-login ssh ${acct} ${env} ${target}`
}

export default function AccessMap() {
  const [data, setData] = useState<Access | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)

  useEffect(() => {
    // 모양이 다른 답(예: 옛 API · 로그인 화면)을 그대로 그리면 화면이 통째로 죽는다 — '모름' 으로
    fetchAccess().then(
      (d) => (d && typeof d.state === 'string' && Array.isArray(d.envs) && Array.isArray(d.people) ? setData(d) : setErr('응답 모양이 이상해요')),
      (e: Error) => setErr(e.message),
    )
  }, [])

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

  const person = data.people.find((p) => p.email === picked) ?? null

  return (
    <div className="access">
      <aside className="card access-people" aria-label="사람">
        <div className="access-colhead">사람</div>
        {data.people.map((p) => (
          <button
            key={p.email}
            type="button"
            className={'access-person' + (picked === p.email ? ' access-person--on' : '')}
            aria-pressed={picked === p.email}
            onClick={() => setPicked(picked === p.email ? null : p.email)}
          >
            <span className={'badge ' + (p.role === 'admin' ? 'access-badge--admin' : 'access-badge--dev')}>{ROLE_LABEL[p.role]}</span>
            <span className="access-person__who">{p.email}</span>
            <span className="access-person__acct">gw {p.gw_account}{p.role === 'developer' ? ' (개인)' : ''} · 서버 {p.server_account}</span>
            {p.note && <span className="access-person__acct">{p.note}</span>}
          </button>
        ))}
        <p className="access-foot">운영자 이름은 나중에 Authentik 에서 가져와요.</p>
      </aside>

      <section className="access-places" aria-label="환경 · gw · 서버">
        {data.envs.map((e) => (
          <div key={e.env} className="card access-env">
            <div className="access-env__head">
              <span className="access-env__name">{e.env}</span>
              <span className="muted">{e.audience}</span>
            </div>
            {e.services.length === 0 && <div className="muted access-empty">목록에 적힌 gw 가 없어요</div>}
            {e.services.map((s) => {
              const on = canGo(person, e.env, s.name)
              return (
                <div key={s.name} className={'access-gw' + (on ? '' : ' access-gw--dim')} data-testid={`gw-${e.env}-${s.name}`}>
                  <div className="access-gw__row">
                    <span className="access-gw__name">{s.name} · gw</span>
                    <span className="mono muted">{s.gw ? `${s.gw.host}${s.gw.port !== 22 ? `:${s.gw.port}` : ''}` : '(gw 주소 없음)'}</span>
                    <span className="mono access-cmd">{on ? sshFor(person, e.env, s.name, true) : `${person?.email ?? ''} 은 못 들어감`}</span>
                  </div>
                  {s.servers.map((v) => (
                    <div key={v.name} className="access-srv">
                      <span>{v.name}</span>
                      <span className="mono muted">{v.addr}</span>
                      <span className="mono access-cmd">{on ? `gw 안에서 ${sshFor(person, e.env, v.name, false)}` : ''}</span>
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
        ))}
      </section>
    </div>
  )
}
