import type { AccessLog } from '../api'

// 이름표(Authentik — IdP 서버가 5분마다 적음)에서 찾은 이름을 이메일 옆에 작게. 서버 탭 · 접속 기록 탭이 같이 쓴다.
//   못 찾으면(두 그룹 밖 · 이름표를 모름) 아무것도 안 그림 — 이메일만 보인다(오류 아님)
//   비활성(Authentik 에서 막힌 계정 — 퇴사 등)은 흐리게 '(비활성)'

type Names = AccessLog['names']

// 키는 이메일(소문자) — 금고 · 접속 기록에 대문자가 섞여 와도 찾는다
export function findName(names: Names | undefined, email: string | null | undefined): { name: string | null; active: boolean } | null {
  if (!names || names.state !== 'ok' || !email) return null
  return names.people?.[email.trim().toLowerCase()] ?? null
}

export default function PersonName({ name, active }: { name?: string | null; active?: boolean | null }) {
  if (!name && active !== false) return null
  return (
    <span className={'person-name' + (active === false ? ' person-name--inactive' : '')}>
      {name}
      {active === false && ' (비활성)'}
    </span>
  )
}
