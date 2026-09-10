import { useState } from 'react'
import Dashboard from './pages/Dashboard'
import Servers from './pages/Servers'
import Versions from './pages/Versions'
import Conf from './pages/Conf'
import Updates from './pages/Updates'
import Cicd from './pages/Cicd'
import Jobs from './pages/Jobs'

const TABS = ['대시보드', '서버', '버전·빌드', '설정', '업데이트', 'CI/CD', '작업이력'] as const
type Tab = (typeof TABS)[number]

function Page({ tab }: { tab: Tab }) {
  switch (tab) {
    case '대시보드': return <Dashboard />
    case '서버': return <Servers />
    case '버전·빌드': return <Versions />
    case '설정': return <Conf />
    case '업데이트': return <Updates />
    case 'CI/CD': return <Cicd />
    case '작업이력': return <Jobs />
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
        <Page tab={tab} />
      </main>
    </div>
  )
}
