import { Fragment, useState, type ReactNode } from 'react'

// 표 읽는 법 한 칸: 이 칸이 무엇을 보여주나(what) + 칸에 나올 수 있는 값 → 뜻(items, 짧게)
export type LegendRow = { term: ReactNode; what: ReactNode; items?: [ReactNode, ReactNode][] }

// '표 읽는 법' — 기본은 접어 두고, 펼치면 칸마다 '무엇을 보여주나' + '값 → 뜻'. 맨 아래 '출처'.
// 펼침 상태는 이 브라우저에만 기억(탭마다) — 저장소를 못 쓰면 매번 접힌 채로.
export default function Legend({ id, rows, source }: { id: string; rows: LegendRow[]; source?: string }) {
  const key = `legend:${id}`
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(key) === '1'
    } catch {
      return false
    }
  })
  return (
    <details
      className="legend"
      open={open}
      onToggle={(e) => {
        const o = (e.currentTarget as HTMLDetailsElement).open
        setOpen(o)
        try {
          localStorage.setItem(key, o ? '1' : '0')
        } catch {
          /* 저장 못 해도 화면은 그대로 */
        }
      }}
    >
      <summary>표 읽는 법</summary>
      <dl className="legend-grid">
        {rows.map((r, i) => (
          <Fragment key={i}>
            <dt>{r.term}</dt>
            <dd>
              <div className="legend-what">{r.what}</div>
              {r.items && (
                // 값 → 뜻 한 쌍씩, 옆으로 흘려서(넓으면 한 줄에 여러 쌍) 높이를 줄임
                <ul className="legend-items">
                  {r.items.map(([value, meaning], j) => (
                    <li key={j}>
                      <span className="legend-v">{value}</span>
                      <span className="legend-m">{meaning}</span>
                    </li>
                  ))}
                </ul>
              )}
            </dd>
          </Fragment>
        ))}
        {source && (
          <>
            <dt>출처</dt>
            <dd className="muted">{source}</dd>
          </>
        )}
      </dl>
    </details>
  )
}
