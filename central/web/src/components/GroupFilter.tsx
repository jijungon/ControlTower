// 고르기 버튼 묶음 — 빌드·배포·config 탭이 같은 것을 씀(그룹 · 빌드 등). 몇 개 안 돼서 드롭다운 대신 알약 버튼(상단 탭과 같은 모양)
export default function GroupFilter({
  groups,
  value,
  onChange,
  label = '그룹',
}: {
  groups: string[]
  value: string
  onChange: (g: string) => void
  label?: string
}) {
  const items: [string, string][] = [['', '전체'], ...groups.map((g): [string, string] => [g, g])]
  return (
    <div className="seg" role="radiogroup" aria-label={`${label} 필터`}>
      <span className="seg-label">{label}</span>
      {items.map(([v, label]) => (
        <button
          key={v || '*'}
          type="button"
          role="radio"
          aria-checked={value === v}
          className={'seg-btn' + (value === v ? ' seg-btn--active' : '')}
          onClick={() => onChange(v)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
