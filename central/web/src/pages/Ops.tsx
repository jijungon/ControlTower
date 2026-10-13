import Jobs from './Jobs'
import Updates from './Updates'

// OS 패치 · 작업이력 — 넓은 화면은 좌우, 좁으면 위아래
export default function Ops() {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">OS 패치 · 작업이력</h1>
        <p className="page-sub">왼쪽: 서버마다 아직 안 깔린 OS 패치 · 오른쪽: ControlTower 가 한 모든 일의 기록</p>
      </div>
      <div className="split">
        <div>
          <Updates />
        </div>
        <div>
          <Jobs />
        </div>
      </div>
    </div>
  )
}
