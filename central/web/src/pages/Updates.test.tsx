import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import Updates from './Updates'

test('서버 행 클릭으로 패키지 목록 펼침/접힘', async () => {
  render(<Updates />)
  // web-01 은 기본 펼침 → openssl 보임
  expect(screen.getByText('openssl')).toBeInTheDocument()

  // web-01 클릭 → 접힘
  await userEvent.click(screen.getByText('web-01'))
  expect(screen.queryByText('openssl')).not.toBeInTheDocument()

  // 다시 클릭 → 펼침
  await userEvent.click(screen.getByText('web-01'))
  expect(screen.getByText('openssl')).toBeInTheDocument()
})
