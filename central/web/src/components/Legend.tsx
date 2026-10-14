import { Fragment, useState, type ReactNode } from 'react'

// '표 읽는 법' — 기본은 접어 두고, 펼치면 '칸 | 뜻' 두 줄 표. 맨 아래 '출처'(이 표가 어디서 온 값인지).
// 펼침 상태는 이 브라우저에만 기억(탭마다) — 저장소를 못 쓰면 매번 접힌 채로.
export default function Legend({ id, rows, source }: { id: string; rows: [ReactNode, ReactNode][]; source?: string }) {
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
        {rows.map(([term, meaning], i) => (
          <Fragment key={i}>
            <dt>{term}</dt>
            <dd>{meaning}</dd>
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
