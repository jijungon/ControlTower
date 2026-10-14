// 표 하나(섹션)의 머리줄: 제목 · 데이터 기준 시각 · [새로고침].
// 새로고침은 '화면 새로고침'(중앙에 저장된 값을 다시 읽음)이다. 서버·GitLab 을 다시 수집하는 건 러너 몫.

// 가장 최근 시각(ISO). 없으면 null.
export function latestTime(times: (string | null | undefined)[]): string | null {
  const t = times.filter((x): x is string => !!x).sort()
  return t.length ? t[t.length - 1] : null
}

// ISO → "2026-10-13 12:03" (보는 사람 시간대)
export function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

// ↻ 아이콘 버튼. 불러오는 동안 돈다. 글자 대신 기호 — 뜻은 마우스를 올리면(title) 보인다.
export function RefreshButton({ label, onClick, busy }: { label: string; onClick: () => void | Promise<unknown>; busy?: boolean }) {
  return (
    <button
      className={'icon-btn' + (busy ? ' icon-btn--spin' : '')}
      onClick={() => onClick()}
      disabled={busy}
      aria-label={label}
      title={busy ? '불러오는 중…' : '새로고침'}
    >
      ↻
    </button>
  )
}

type Props = {
  title: string
  sub?: string
  asOf?: string | null // 데이터 기준 시각(수집 시각 중 가장 최근)
  onRefresh?: () => void | Promise<unknown>
  busy?: boolean
  source?: string // 이 표가 어디서 온 값인지(관리할 때 헷갈리지 않게)
}

export default function SectionHead({ title, sub, asOf, onRefresh, busy, source }: Props) {
  return (
    <>
    <div className="section-head">
      <h2 className="section-title">{title}</h2>
      {sub && <span className="section-sub">{sub}</span>}
      <span className="spacer" />
      <span className="section-asof">{asOf ? `데이터 기준 ${fmtTime(asOf)}` : '아직 수집 없음'}</span>
      {onRefresh && <RefreshButton label={`${title} 새로고침`} onClick={onRefresh} busy={busy} />}
    </div>
    {source && <p className="section-source">출처: {source}</p>}
    </>
  )
}

// 새로고침 버튼용: 여러 로더를 한 번에 돌리고 busy 표시
export async function runAll(setBusy: (b: boolean) => void, loaders: (() => Promise<unknown>)[]) {
  setBusy(true)
  try {
    await Promise.all(loaders.map((l) => l()))
  } finally {
    setBusy(false)
  }
}
