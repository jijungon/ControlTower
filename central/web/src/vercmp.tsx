// 버전 비교 — "같은 종류 중 최신이 아닌 버전" 을 빨간 칸으로 표시할 때 쓴다.

// "3.10.12" → [3,10,12], "v18" → [18], "0.1.3-java17" → [0,1,3]. 숫자가 없으면 [].
export function verParts(v?: string | null): number[] {
  const m = (v ?? '').match(/\d+(?:\.\d+)*/)
  return m ? m[0].split('.').map(Number) : []
}

export function cmpVer(a: number[], b: number[]): number {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0)
    if (d !== 0) return Math.sign(d)
  }
  return 0
}

// 같은 종류(key) 안에서 가장 높은 버전. 버전 숫자가 없는 값은 비교에서 뺀다.
export function newestBy<T>(rows: T[], pick: (r: T) => [string, string] | null): Map<string, string> {
  const best = new Map<string, string>()
  for (const r of rows) {
    const kv = pick(r)
    if (!kv || verParts(kv[1]).length === 0) continue
    const cur = best.get(kv[0])
    if (!cur || cmpVer(verParts(kv[1]), verParts(cur)) > 0) best.set(kv[0], kv[1])
  }
  return best
}

export function isOld(kv: [string, string] | null, newest: Map<string, string>): boolean {
  if (!kv) return false
  const top = newest.get(kv[0])
  return !!top && verParts(kv[1]).length > 0 && cmpVer(verParts(kv[1]), verParts(top)) < 0
}

// 빨간 칸(오래됨) 또는 일반 버전 글자. split = 'image:tag' 를 두 줄로(긴 이미지 이름이 칸을 넓히지 않게)
export function Ver({ text, old, newest, split }: { text: string; old: boolean; newest?: string; split?: boolean }) {
  const i = split ? text.lastIndexOf(':') : -1
  const body =
    i > 0 ? (
      <>
        {text.slice(0, i)}
        <br />
        {text.slice(i)}
      </>
    ) : (
      text
    )
  return old ? (
    <span className="ver ver--old" title={`최신(${newest})보다 오래됨`} style={i > 0 ? { display: 'inline-block' } : undefined}>
      ⚠ {body}
    </span>
  ) : (
    <span className="ver" style={i > 0 ? { display: 'inline-block' } : undefined}>
      {body}
    </span>
  )
}
