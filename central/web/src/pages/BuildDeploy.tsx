import CicdCompare from './CicdCompare'

// 빌드·배포 탭 = CI 가 '어떻게' 빌드·배포하나(방식만). 버전은 config 탭, 서버에 깔린 도구는 서버 탭.
export default function BuildDeploy() {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">빌드 · 배포</h1>
        <p className="page-sub">CI 가 어떻게 빌드·배포하나 — 버전은 config 탭, 서버에 깔린 도구는 서버 탭</p>
      </div>
      <CicdCompare />
    </div>
  )
}
