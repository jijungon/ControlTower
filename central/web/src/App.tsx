import { useEffect, useState } from 'react'
import { developerOnly, fetchMe } from './api'
import AuthExpiredBanner from './components/AuthExpiredBanner'
import HostStatusBar from './components/HostStatusBar'
import VersionTag from './components/VersionTag'
import Dashboard from './pages/Dashboard'
import Servers from './pages/Servers'
import BuildDeploy from './pages/BuildDeploy'
import ConfigRepo from './pages/ConfigRepo'
import Ops from './pages/Ops'

// 서버(IdP 연동 후 서버 ↔ 항목 연결 자리 + /etc 설정 파일) → config(repo / center — 무엇으로 만드나)
// → 빌드·배포(어떻게 배포하나) → OS 패치·작업이력
const TABS = ['대시보드', '서버', 'config', '빌드·배포', 'OS 패치·작업이력'] as const
type Tab = (typeof TABS)[number]
// 개발자(server-admin 아님)는 서버 탭만 — 서버 탭 안의 /etc 칸(운영자용)도 숨김. API 도 같은 선으로 막힘
const DEV_TABS: readonly Tab[] = ['서버']

function Page({ tab, go, devOnly }: { tab: Tab; go: (t: Tab) => void; devOnly: boolean }) {
  switch (tab) {
    case '대시보드': return <Dashboard onGo={(t) => TABS.includes(t as Tab) && go(t as Tab)} />
    case '서버': return <Servers showConf={!devOnly} />
    case '빌드·배포': return <BuildDeploy />
    case 'config': return <ConfigRepo />
    case 'OS 패치·작업이력': return <Ops />
  }
}

export default function App() {
  const [tab, setTab] = useState<Tab>('대시보드')
  // 누가 보나 — 알기 전에는 탭을 그리지 않는다(개발자에게 다른 탭이 잠깐 떠서 403 이 나지 않게). 못 알아내면 전부(API 가 막음)
  const [devOnly, setDevOnly] = useState<boolean | null>(null)
  useEffect(() => {
    fetchMe().then(
      (me) => setDevOnly(developerOnly(me)),
      () => setDevOnly(false),
    )
  }, [])
  const tabs = devOnly ? DEV_TABS : TABS
  const current = tabs.includes(tab) ? tab : tabs[0]

  return (
    <div className="app">
      <header className="global-nav">
        <span className="brand">Control Tower</span>
        <span className="spacer" />
        <VersionTag />
      </header>
      <AuthExpiredBanner />
      <HostStatusBar />

      <nav className="sub-nav">
        {devOnly !== null && tabs.map((t) => (
          <button
            key={t}
            className={'tab' + (t === current ? ' tab--active' : '')}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </nav>

      <main className="content">
        {devOnly === null ? <div className="card placeholder">불러오는 중…</div> : <Page tab={current} go={setTab} devOnly={devOnly} />}
      </main>
    </div>
  )
}
