import { Fragment, useEffect, useState, type ReactNode } from 'react'
import { fetchVersion, type AppVersion } from '../api'

// 화면 맨 위 오른쪽 — 지금 도는 ControlTower 버전. 반영이 됐는지 화면에서 바로 본다.
//   v0.0.68 · 이슈 #59 · <커밋> · 10/28 10:15 반영  (이슈가 없으면 이슈 칸만 빠짐)
// 버전 = 합칠 때 GitHub 작업이 단 태그 v0.0.{PR}+{이슈}(.github/scripts/version-tag.sh), 반영 쪽이 CT_VERSION 으로 넘긴다.
// 버전을 지어내지 않는다: 반영할 때 안 넣었으면(dev) · 못 불러오면 '버전 모름'.
const REPO = 'https://github.com/jijungon/ControlTower'
const unset = (v?: string | null) => !v || v === 'dev'

function when(iso?: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

// 'v0.0.68+59.60' → PR 68 · 이슈 59, 60. 다른 모양(예: v1.2.0)은 글자 그대로
function parseVersion(v: string): { label: string; pr: string | null; issues: string[] } {
  const [base, extra = ''] = v.split('+', 2)
  const pr = /^v0\.0\.(\d+)$/.exec(base)?.[1] ?? null
  return { label: base, pr, issues: extra.split('.').filter((n) => /^\d+$/.test(n)) }
}

const link = (href: string, text: string) => (
  <a className="version-link" href={href} target="_blank" rel="noreferrer">
    {text}
  </a>
)

export default function VersionTag() {
  const [v, setV] = useState<AppVersion | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    fetchVersion()
      .then((d) => setV(d))
      .catch(() => setErr(true))
  }, [])

  if (err) return <span className="meta" title="ControlTower 에서 버전을 불러오지 못함">버전 모름</span>
  if (!v) return null
  const at = when(v.started_at)
  if (unset(v.build) && unset(v.version))
    return (
      <span className="meta" title="반영할 때 CT_BUILD(커밋) · CT_VERSION 을 넣지 않아 어떤 버전인지 몰라요">
        버전 모름(dev){at ? ` · ${at} 시작` : ''}
      </span>
    )

  const parts: ReactNode[] = []
  if (!unset(v.version)) {
    const pv = parseVersion(v.version)
    parts.push(pv.pr ? link(`${REPO}/pull/${pv.pr}`, pv.label) : pv.label)
    if (pv.issues.length)
      parts.push(
        <>
          이슈{' '}
          {pv.issues.map((n, i) => (
            <Fragment key={n}>
              {i > 0 && ' · '}
              {link(`${REPO}/issues/${n}`, `#${n}`)}
            </Fragment>
          ))}
        </>,
      )
  }
  if (!unset(v.build)) parts.push(link(`${REPO}/commit/${v.build}`, v.build))

  return (
    <span className="meta" title={`버전 ${v.version} · 커밋 ${v.build}${v.started_at ? ` · 반영 ${v.started_at}` : ''}`}>
      {parts.map((p, i) => (
        <Fragment key={i}>
          {i > 0 && ' · '}
          {p}
        </Fragment>
      ))}
      {at ? ` · ${at} 반영` : ''}
    </span>
  )
}
