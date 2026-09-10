import { useState } from 'react'
import Servers from './pages/Servers'
import Placeholder from './pages/Placeholder'

const TABS = ['대시보드', '서버', '버전·빌드', '설정', '업데이트', 'CI/CD', '작업이력'] as const
type Tab = (typeof TABS)[number]

export default function App() {
  const [tab, setTab] = useState<Tab>('서버')

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
        {tab === '서버' ? <Servers /> : <Placeholder title={tab} />}
      </main>
    </div>
  )
}
