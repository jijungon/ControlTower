// 그룹 고르기 — 빌드·배포·config 탭이 같은 것을 씀. 그룹이 몇 개 안 돼서 드롭다운 대신 알약 버튼(상단 탭과 같은 모양)
export default function GroupFilter({ groups, value, onChange }: { groups: string[]; value: string; onChange: (g: string) => void }) {
  const items: [string, string][] = [['', '전체'], ...groups.map((g): [string, string] => [g, g])]
  return (
    <div className="seg" role="radiogroup" aria-label="그룹 필터">
      <span className="seg-label">그룹</span>
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
