import { useEffect, useState } from 'react'
import { fetchVersion, type AppVersion } from '../api'

// 화면 맨 위 오른쪽 — 지금 도는 ControlTower 버전(커밋 · 반영 시각). 반영이 됐는지 화면에서 바로 본다.
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
  const label = [unset(v.version) ? null : v.version, unset(v.build) ? null : v.build].filter(Boolean).join(' · ')
  return (
    <span className="meta" title={`버전 ${v.version} · 커밋 ${v.build}${v.started_at ? ` · 반영 ${v.started_at}` : ''}`}>
      {unset(v.build) ? (
        label
      ) : (
        <a className="version-link" href={`${REPO}/commit/${v.build}`} target="_blank" rel="noreferrer">
          {label}
        </a>
      )}
      {at ? ` · ${at} 반영` : ''}
    </span>
  )
}
