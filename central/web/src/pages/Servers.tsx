import AccessMap from '../components/AccessMap'
import Conf from './Conf'

// 서버 탭 = IdP 연동 뒤, 서버 정보(목록·접속)를 IdP(금고 목록)에서 받아 보여 주는 곳.
// 예전 ~/.ssh/config 임포트 목록(IP · 접속키 · 깔린 도구)은 계속 안 쓴다(API·runner 는 남김) — 원본은 금고 목록 하나.
// '누가 · 어디로' 는 보기 전용 (2026-10-27) — 운영자 '목록 고치기'(gw · 서버)는 CT_INVENTORY_EDIT 를 켰을 때만.
// config · 빌드·배포 항목과의 연결은 다음.
// /etc 설정 파일(드리프트·적용)은 운영자용 — 개발자에게는 숨김(showConf=false).
export default function Servers({ showConf = true }: { showConf?: boolean }) {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">서버</h1>
        <p className="page-sub">누가 어느 gw · 서버에 어떤 계정으로 들어가는지 — 금고 목록에서</p>
      </div>

      <div className="section-head">
        <h2 className="section-title">누가 · 어디로</h2>
        <span className="section-sub">금고 목록 — 고치기는 gw 에서 idp-login service add · server add · user add (켜 두면 운영자는 여기서 gw · 서버도)</span>
      </div>
      <AccessMap />

      {showConf && <Conf />}
    </div>
  )
}
