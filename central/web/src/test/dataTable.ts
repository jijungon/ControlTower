import { waitFor } from '@testing-library/react'

// 표는 데이터가 오기 전에도 그려진다('불러오는 중…'). findByRole('table') 은 그 빈 표에서 바로 끝나서,
// 느린 CI 에서는 데이터 확인이 빈 표를 보고 깨졌다 → 본문 줄이 생길 때까지 기다린 뒤 그 표를 돌려준다.
export function findDataTable(selector = 'table.grid--nowrap'): Promise<HTMLElement> {
  return waitFor(() => {
    const t = document.querySelector<HTMLElement>(selector)
    if (!t || !t.querySelector(':scope > tbody > tr')) throw new Error('표에 아직 데이터 줄이 없음')
    return t
  })
}
