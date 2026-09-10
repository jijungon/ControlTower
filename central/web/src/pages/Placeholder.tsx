export default function Placeholder({ title }: { title: string }) {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">{title}</h1>
        <p className="page-sub">구현 예정</p>
      </div>
      <div className="placeholder">이 탭은 아직 스캐폴드 단계입니다.</div>
    </div>
  )
}
