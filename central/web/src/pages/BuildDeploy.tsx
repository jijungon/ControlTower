import CicdCompare from './CicdCompare'
import Cicd from './Cicd'
import Versions from './Versions'

// 빌드·배포 탭 = 서비스 비교표 + 버전 + 파이프라인 (예전 '버전·빌드' + 'CI/CD')
export default function BuildDeploy() {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">빌드 · 배포</h1>
        <p className="page-sub">서비스가 어떤 버전·방식으로 빌드되고 배포되나 — repo·center CI 와 빌드 서버에서 읽은 값</p>
      </div>
      <CicdCompare />
      <Versions />
      <Cicd />
    </div>
  )
}
