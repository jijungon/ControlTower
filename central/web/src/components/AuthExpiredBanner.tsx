import { useAuthExpired } from '../authExpiry'

// 로그인이 만료되면 화면 맨 위에 한 줄 — 각 표의 '못 불러옴' 이 서버 고장처럼 보이지 않게
export default function AuthExpiredBanner() {
  const expired = useAuthExpired()
  if (!expired) return null
  return (
    <div className="auth-expired" role="alert">
      <span>로그인이 만료됐어요 — 새로고침해 주세요</span>
      <button type="button" className="btn btn--sm" onClick={() => window.location.reload()}>
        새로고침
      </button>
    </div>
  )
}
