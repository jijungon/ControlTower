import Conf from './Conf'

// 서버 탭 = IdP 연동 뒤, 서버 정보(목록·접속)를 IdP 에서 받아 config · 빌드·배포 항목(서비스 · dev·stg·prod)과 잇는 곳.
// 지금은 서버 정보를 보여주지 않는다 — 예전 ~/.ssh/config 임포트 목록(IP · 접속키 · 깔린 도구)은 뺐음(API·runner 는 남김).
// /etc 설정 파일(드리프트·적용)은 그대로.
export default function Servers() {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">서버</h1>
        <p className="page-sub">IdP 연동 후 — 서버 정보를 IdP 에서 받아 config · 빌드·배포 항목과 연결하는 곳</p>
      </div>

      <div className="section-head">
        <h2 className="section-title">서버 ↔ 항목 연결</h2>
        <span className="section-sub">IdP 연동 후</span>
      </div>
      <div className="card" style={{ marginBottom: 24 }}>
        <div className="placeholder" style={{ padding: '24px 16px' }}>
          서버 목록은 <b>IdP 연동 후</b> IdP 에서 가져와요. 그때 서버마다 <b>config · 빌드·배포 항목(서비스 · dev·stg·prod)</b>과 연결해요.
          <div style={{ marginTop: 6, fontSize: 13 }}>예전 ~/.ssh/config 로 모은 서버 목록(IP · 접속키 · 깔린 도구)은 뺐어요.</div>
        </div>
      </div>

      <Conf />
    </div>
  )
}
