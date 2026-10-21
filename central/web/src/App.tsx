import { useState } from 'react'
import HostStatusBar from './components/HostStatusBar'
import Dashboard from './pages/Dashboard'
import Servers from './pages/Servers'
import BuildDeploy from './pages/BuildDeploy'
import ConfigRepo from './pages/ConfigRepo'
import Ops from './pages/Ops'

// 서버(IdP 연동 후 서버 ↔ 항목 연결 자리 + /etc 설정 파일) → config(repo / center — 무엇으로 만드나)
// → 빌드·배포(어떻게 배포하나) → OS 패치·작업이력
const TABS = ['대시보드', '서버', 'config', '빌드·배포', 'OS 패치·작업이력'] as const
type Tab = (typeof TABS)[number]

function Page({ tab, go }: { tab: Tab; go: (t: Tab) => void }) {
  switch (tab) {
    case '대시보드': return <Dashboard onGo={(t) => TABS.includes(t as Tab) && go(t as Tab)} />
    case '서버': return <Servers />
    case '빌드·배포': return <BuildDeploy />
    case 'config': return <ConfigRepo />
    case 'OS 패치·작업이력': return <Ops />
  }
}

export default function App() {
  const [tab, setTab] = useState<Tab>('대시보드')

  return (
    <div className="app">
      <header className="global-nav">
        <span className="brand">Control Tower</span>
        <span className="spacer" />
        <span className="meta">사내망 전용 · 단일 머신(test)</span>
      </header>
      <HostStatusBar />

      <nav className="sub-nav">
        {TABS.map((t) => (
          <button
            key={t}
            className={'tab' + (t === tab ? ' tab--active' : '')}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </nav>

      <main className="content">
        <Page tab={tab} go={setTab} />
      </main>
    </div>
  )
}
