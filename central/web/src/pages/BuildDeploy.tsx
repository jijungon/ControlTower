import { useState } from 'react'
import CollectButton from '../components/CollectButton'
import CicdCompare from './CicdCompare'

// 빌드·배포 탭 = CI 가 '어떻게' 빌드·배포하나(방식만). 버전은 config 탭, 서버에 깔린 도구는 서버 탭.
export default function BuildDeploy() {
  const [round, setRound] = useState(0) // 다시 수집이 끝나면 표를 새로 불러옴
  return (
    <div>
      <div className="page-head page-head--row">
        <div>
          <h1 className="page-title">빌드 · 배포</h1>
          <p className="page-sub">CI 가 어떻게 빌드·배포하나</p>
        </div>
        <CollectButton onDone={() => setRound((n) => n + 1)} />
      </div>
      <CicdCompare key={round} />
    </div>
  )
}
