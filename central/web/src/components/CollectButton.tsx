import { useEffect, useRef, useState } from 'react'
import { fetchCollectStatus, requestCollect, type CollectStatus } from '../api'
import { fmtTime } from './SectionHead'

// [다시 수집] — GitLab 을 다시 읽어 오라고 수집기에 요청한다(↻ 는 이미 모은 값을 화면에 다시 불러오기만).
// 중앙은 키·토큰이 없어 직접 못 모은다 → 요청만 남기고, ControlTower 서버의 수집기(runner agent)가 가져가 처리.
// 요청됨 → 수집 중 → 완료(표를 새로 불러옴) / 실패(이유 한 줄). 기다리는 동안 2초마다 상태 확인.
export default function CollectButton({ onDone, kind = 'shape' }: { onDone: () => void; kind?: string }) {
  const [st, setSt] = useState<CollectStatus | null>(null)
  const [err, setErr] = useState(false)
  const watching = useRef<number | null>(null) // 기다리던 요청 — 끝나면 한 번만 onDone
  const req = st?.request ?? null
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
  useEffect(() => {
    if (!busy) return
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [busy])

  const click = async () => {
    try {
      const r = await requestCollect(kind)
      watching.current = r.id
      await load()
    } catch {
      setErr(true)
    }
  }

  const alive = st?.collector?.alive ?? false
  let text: string | null = null
  let tone = ''
  let title: string | undefined
  if (err) [text, tone] = ['ControlTower 에 못 닿음', 'fail']
  else if (req?.status === 'pending') {
    text = alive ? '요청됨 — 수집기를 기다리는 중' : '요청됨 — ⚠ 수집기가 꺼져 있어요'
    tone = alive ? '' : 'warn'
    title = alive ? undefined : 'ControlTower 서버에서 수집기를 켜야 해요: python -m runner.cli agent'
  } else if (req?.status === 'running') text = '수집 중 — GitLab 을 다시 읽는 중'
  else if (req?.status === 'done') [text, tone, title] = [`완료 · ${fmtTime(req.finished_at ?? '')}`, 'ok', req.message ?? undefined]
  else if (req?.status === 'failed') [text, tone, title] = [`실패 · ${req.message ?? '이유 모름'}`, 'fail', req.message ?? undefined]
  else if (st && !alive) [text, title] = ['수집기 꺼짐', 'ControlTower 서버에서 수집기를 켜야 버튼이 동작해요: python -m runner.cli agent']

  return (
    <span className="collect">
      <button
        type="button"
        className="btn"
        onClick={click}
        disabled={busy}
        title="GitLab 을 다시 읽어 오라고 수집기에 요청 — ↻ 는 이미 모은 값을 화면에 다시 불러오기만"
      >
        {busy ? '수집 중…' : '다시 수집'}
      </button>
      {text && (
        <span className={`collect-state${tone ? ` collect-state--${tone}` : ''}`} title={title} role="status">
          {text}
        </span>
      )}
    </span>
  )
}
