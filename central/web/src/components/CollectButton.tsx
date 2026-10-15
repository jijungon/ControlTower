import { useEffect, useRef, useState } from 'react'
import { fetchCollectStatus, requestCollect, type CollectStatus } from '../api'
import { fmtTime } from './SectionHead'

// [다시 수집] — GitLab 을 다시 읽어 오라고 수집기에 요청한다. 끝나면 표를 새로 불러온다(따로 ↻ 없음).
// 옆 글은 평소엔 '데이터 기준 시각' 하나(표 머리줄의 시각과 겹치지 않게 여기에만), 수집할 땐 진행 상태.
// 중앙은 키·토큰이 없어 직접 못 모은다 → 요청만 남기고, ControlTower 서버의 수집기(runner agent)가 가져가 처리.
// 수집기가 꺼져 있으면 버튼도 꺼짐(누르면 영원히 '요청됨'이 되니까) — 10초마다 확인해서 켜지면 다시 켜짐.
const HOW_TO_START = '수집기 켜는 법 — 서버: docker compose 의 collector / 내 PC: make agent (python -m runner.cli agent)'

const RECENT_MS = 5 * 60 * 1000 // 끝난 지 5분 안이면 '방금 갱신'

export default function CollectButton({ onDone, asOf, kind = 'shape' }: { onDone: () => void; asOf?: string | null; kind?: string }) {
  const [st, setSt] = useState<CollectStatus | null>(null)
  const [err, setErr] = useState(false)
  const watching = useRef<number | null>(null) // 기다리던 요청 — 끝나면 한 번만 onDone
  const req = st?.request ?? null
  const alive = st?.collector?.alive ?? false
  const busy = req?.status === 'pending' || req?.status === 'running'

  const load = async () => {
    try {
      const s = await fetchCollectStatus(kind)
      setSt(s)
      setErr(false)
      const r = s.request
      if (r && (r.status === 'pending' || r.status === 'running')) watching.current = r.id
      else if (r && watching.current === r.id) {
        watching.current = null
        if (r.status === 'done') onDone()
      }
    } catch {
      setErr(true)
    }
  }

  useEffect(() => {
    load()
  }, [])
  // 수집 중이면 2초마다, 수집기가 꺼져 있으면 10초마다(켜지면 버튼을 다시 켜려고) 상태 확인
  useEffect(() => {
    if (!st || (!busy && alive)) return
    const t = setInterval(load, busy && alive ? 2000 : 10000)
    return () => clearInterval(t)
  }, [st === null, busy, alive])

  const click = async () => {
    try {
      const r = await requestCollect(kind)
      watching.current = r.id
    } catch {
      /* 수집기가 막 꺼진 경우(409) — 아래 load 가 '수집기 꺼짐'으로 보여 줌 */
    }
    await load()
  }

  const dataAt = asOf ? `데이터 기준 ${fmtTime(asOf)}` : '아직 수집 없음'
  const recent = req?.status === 'done' && !!req.finished_at && Date.now() - new Date(req.finished_at).getTime() < RECENT_MS
  let text: string = dataAt
  let tone = ''
  let title: string | undefined
  if (err) [text, tone] = [`ControlTower 에 못 닿음 · ${dataAt}`, 'fail']
  else if (st && !alive)
    [text, tone, title] = [req?.status === 'pending' ? '요청됨 — 수집기가 꺼져 있어요(켜면 바로 처리)' : `수집기 꺼짐 · ${dataAt}`, 'warn', HOW_TO_START]
  else if (req?.status === 'pending') text = '요청됨 — 곧 시작'
  else if (req?.status === 'running') text = '수집 중 — GitLab 을 다시 읽는 중'
  else if (req?.status === 'failed') [text, tone, title] = [`실패 · ${req.message ?? '이유 모름'} · ${dataAt}`, 'fail', req.message ?? undefined]
  else if (recent) [text, tone, title] = [`${dataAt} · 방금 갱신`, 'ok', req?.message ?? undefined]

  return (
    <span className="collect">
      <button
        type="button"
        className="btn"
        onClick={click}
        disabled={!st || busy || !alive}
        title={
          st && !alive
            ? `수집기가 꺼져 있어 누를 수 없어요 — ${HOW_TO_START}`
            : 'GitLab 을 다시 읽어 와서 표를 새로 불러와요(1분 안팎)'
        }
      >
        {busy && alive ? '수집 중…' : '다시 수집'}
      </button>
      <span className={`collect-state${tone ? ` collect-state--${tone}` : ''}`} title={title} role="status">
        {text}
      </span>
    </span>
  )
}
