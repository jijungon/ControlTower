import { useState } from 'react'

// 표 아래 페이지 넘김 — '1–10 / 75 · ‹ 1/8 › · 10개 | 20개'. 몇 개씩 볼지는 표마다 이 브라우저에 기억.
export const PAGE_SIZES = [10, 20] as const

export function usePageSize(id: string): [number, (n: number) => void] {
  const key = `pager:${id}`
  const [size, setSize] = useState<number>(() => {
    try {
      const n = Number(localStorage.getItem(key))
      return (PAGE_SIZES as readonly number[]).includes(n) ? n : PAGE_SIZES[0]
    } catch {
      return PAGE_SIZES[0]
    }
  })
  const set = (n: number) => {
    setSize(n)
    try {
      localStorage.setItem(key, String(n))
    } catch {
      /* 저장 못 해도 화면은 그대로 */
    }
  }
  return [size, set]
}

export default function Pager({
  label,
  page,
  size,
  total,
  onPage,
  onSize,
}: {
  label: string
  page: number // 0 부터
  size: number
  total: number
  onPage: (p: number) => void
  onSize: (n: number) => void
}) {
  const pages = Math.max(1, Math.ceil(total / size))
  if (total === 0) return null
  const from = page * size + 1
  const to = Math.min(total, (page + 1) * size)
  return (
    <nav className="pager" aria-label={`${label} 페이지`}>
      <span className="muted">
        {from}–{to} / {total}
      </span>
      <span className="pager-nav">
        <button type="button" className="icon-btn" aria-label={`${label} 이전 페이지`} disabled={page <= 0} onClick={() => onPage(page - 1)}>
          ‹
        </button>
        <span className="mono">
          {page + 1}/{pages}
        </span>
        <button type="button" className="icon-btn" aria-label={`${label} 다음 페이지`} disabled={page >= pages - 1} onClick={() => onPage(page + 1)}>
          ›
        </button>
      </span>
      <span className="seg" role="radiogroup" aria-label={`${label} 한 번에 보기`}>
        {PAGE_SIZES.map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={size === n}
            className={'seg-btn' + (size === n ? ' seg-btn--active' : '')}
            onClick={() => {
              onSize(n)
              onPage(0)
            }}
          >
            {n}개
          </button>
        ))}
      </span>
    </nav>
  )
}
