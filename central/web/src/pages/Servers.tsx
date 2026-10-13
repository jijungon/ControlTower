import { useEffect, useState } from 'react'
import { createGroup, fetchGroups, fetchServers, fetchVersions, setServerMeta, type Group, type Server, type VersionRow } from '../api'
import SectionHead, { latestTime, runAll } from '../components/SectionHead'
import Conf from './Conf'
import { isOld, newestBy, Ver } from '../vercmp'

const TOOL_ORDER = ['node', 'npm', 'java', 'python', 'docker']

function authCell(s: Server) {
  if (s.needs_2fa === true) return <span className="badge badge--warn">2FA</span>
  if (s.needs_2fa === false) return <span className="muted">키만</span>
  return <span className="muted">—</span>
}

export default function Servers() {
  const [q, setQ] = useState('')
  const [servers, setServers] = useState<Server[] | null>(null)
  const [groups, setGroups] = useState<Group[]>([])
  const [err, setErr] = useState(false)

  const [filterGroup, setFilterGroup] = useState<number | 'all'>('all')
  const [filterTag, setFilterTag] = useState('')
  const [newGroup, setNewGroup] = useState('')

  const [editId, setEditId] = useState<number | null>(null)
  const [editGroup, setEditGroup] = useState<number | ''>('')
  const [editTags, setEditTags] = useState('')
  const [msg, setMsg] = useState<string | null>(null)

  const [busy, setBusy] = useState(false)

  const load = () =>
    fetchServers()
      .then((r) => {
        setServers(r)
        setErr(false)
      })
      .catch(() => setErr(true))
  const loadGroups = () => fetchGroups().then(setGroups).catch(() => setGroups([]))
  const [tools, setTools] = useState<Record<string, Record<string, string>>>({})
  const loadTools = () =>
    fetchVersions()
      .then((rows: VersionRow[]) => {
        const m: Record<string, Record<string, string>> = {}
        for (const r of Array.isArray(rows) ? rows : []) if (r.kind === 'server' && r.tools) m[r.name] = r.tools
        setTools(m)
      })
      .catch(() => setTools({}))

  useEffect(() => {
    load()
    loadGroups()
    loadTools()
  }, [])

  function startEdit(s: Server) {
    setEditId(s.id)
    setEditGroup(s.group_id ?? '')
    setEditTags((s.tags ?? []).join(', '))
    setMsg(null)
  }

  async function saveEdit(id: number) {
    try {
      await setServerMeta(id, {
        group_id: editGroup === '' ? null : Number(editGroup),
        tags: editTags.split(',').map((t) => t.trim()).filter(Boolean),
      })
      setEditId(null)
      await load()
      await loadGroups()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '저장 실패')
    }
  }

  async function addGroup() {
    const name = newGroup.trim()
    if (!name) return
    try {
      await createGroup(name)
      setNewGroup('')
      await loadGroups()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '그룹 생성 실패')
    }
  }

  const rows = (servers ?? []).filter((s) => {
    const hay = `${s.hostname} ${s.ip ?? ''} ${s.ssh_user}`.toLowerCase()
    if (!hay.includes(q.toLowerCase())) return false
    if (filterGroup !== 'all' && s.group_id !== filterGroup) return false
    if (filterTag && !(s.tags ?? []).some((t) => t.toLowerCase().includes(filterTag.toLowerCase()))) return false
    return true
  })

  // 같은 도구(node 끼리…) 중 최신이 아니면 빨간 칸
  const toolPairs = Object.values(tools).flatMap((t) => Object.entries(t))
  const newestTool = newestBy(toolPairs, (kv) => kv)
  const toolsCell = (host: string) => {
    const t = tools[host]
    if (!t || Object.keys(t).length === 0) return <span className="muted">—</span>
    const rank = (n: string) => (TOOL_ORDER.includes(n) ? TOOL_ORDER.indexOf(n) : 99)
    const names = Object.keys(t).sort((a, b) => rank(a) - rank(b))
    return names.map((n) => (
      <span key={n} style={{ marginRight: 6 }}>
        <Ver text={`${n} ${t[n]}`} old={isOld([n, t[n]], newestTool)} newest={`${n} ${newestTool.get(n)}`} />
      </span>
    ))
  }

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">서버 · 접속키 인벤토리</h1>
        <p className="page-sub">
          ~/.ssh/config 기준 · 그룹·태그로 묶어 보기{servers ? ` · ${servers.length}대` : ''}
        </p>
      </div>

      <SectionHead
        title="서버 목록"
        sub="접속 키 · 접속 확인"
        asOf={latestTime((servers ?? []).map((s) => s.last_checked_at))}
        onRefresh={() => runAll(setBusy, [load, loadGroups, loadTools])}
        busy={busy}
        source="내 PC 의 ~/.ssh/config(runner import) · 접속 확인(runner test·probe) · 깔린 도구 = 서버마다 SSH 로 node/java/docker --version(runner versions)"
      />

      <div className="toolbar" style={{ flexWrap: 'wrap' }}>
        <input className="search" placeholder="서버 · IP · user 검색" value={q} onChange={(e) => setQ(e.target.value)} />
        <select
          className="search"
          style={{ minWidth: 160 }}
          value={filterGroup}
          onChange={(e) => setFilterGroup(e.target.value === 'all' ? 'all' : Number(e.target.value))}
        >
          <option value="all">그룹 전체</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name} ({g.count})
            </option>
          ))}
        </select>
        <input className="search" style={{ minWidth: 160 }} placeholder="태그 필터" value={filterTag} onChange={(e) => setFilterTag(e.target.value)} />
        <span style={{ flex: 1 }} />
        <input className="search" style={{ minWidth: 140 }} placeholder="새 그룹 이름" value={newGroup} onChange={(e) => setNewGroup(e.target.value)} />
        <button className="btn" onClick={addGroup}>그룹 추가</button>
      </div>

      {msg && <div className="card" style={{ padding: '10px 14px', marginBottom: 12, color: 'var(--danger,#b3261e)' }}>{msg}</div>}

      <div className="card">
        <table className="grid">
          <thead>
            <tr>
              <th>서버</th>
              <th>IP</th>
              <th>user</th>
              <th>인증</th>
              <th>그룹</th>
              <th>태그</th>
              <th>키</th>
              <th>깔린 도구</th>
              <th>편집</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id}>
                <td>
                  <span
                    className={`dot dot--${s.status === 'online' ? 'online' : 'unknown'}`}
                    title={s.last_checked_at ? `${s.status} · 확인 ${s.last_checked_at}` : s.status}
                  />
                  {s.hostname}
                </td>
                <td className="mono">{s.ip ?? '—'}</td>
                <td>{s.ssh_user}</td>
                <td>{authCell(s)}</td>
                {editId === s.id ? (
                  <>
                    <td>
                      <select className="search" style={{ height: 30, minWidth: 120 }} value={editGroup} onChange={(e) => setEditGroup(e.target.value === '' ? '' : Number(e.target.value))}>
                        <option value="">(없음)</option>
                        {groups.map((g) => (
                          <option key={g.id} value={g.id}>{g.name}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input className="search" style={{ height: 30, minWidth: 140 }} placeholder="태그, 쉼표로" value={editTags} onChange={(e) => setEditTags(e.target.value)} />
                    </td>
                    <td className="mono">{s.credential_alias ?? '—'}</td>
                    <td>{toolsCell(s.hostname)}</td>
                    <td>
                      <button className="btn btn--sm btn--primary" onClick={() => saveEdit(s.id)}>저장</button>
                      <button className="btn btn--sm" onClick={() => setEditId(null)}>취소</button>
                    </td>
                  </>
                ) : (
                  <>
                    <td>{s.group ? <span className="tag">{s.group}</span> : <span className="muted">—</span>}</td>
                    <td>
                      {(s.tags ?? []).length > 0 ? (
                        (s.tags ?? []).map((t) => (
                          <span key={t} className="tag" style={{ marginRight: 4, cursor: 'pointer' }} onClick={() => setFilterTag(t)}>
                            {t}
                          </span>
                        ))
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="mono">{s.credential_alias ?? '—'}</td>
                    <td>{toolsCell(s.hostname)}</td>
                    <td>
                      <button className="btn btn--sm" onClick={() => startEdit(s)}>편집</button>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>

        {!servers && !err && <div className="placeholder" style={{ padding: '28px 16px' }}>불러오는 중…</div>}
        {servers && servers.length === 0 && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            아직 임포트된 서버가 없습니다 — <span className="mono">python -m runner.cli import</span>
          </div>
        )}
        {servers && servers.length > 0 && rows.length === 0 && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>필터에 맞는 서버가 없습니다.</div>
        )}
        {err && (
          <div className="placeholder" style={{ padding: '28px 16px' }}>
            API에 연결하지 못했습니다 — <span className="mono">make dev</span> 로 중앙 API를 띄우세요.
          </div>
        )}
      </div>

      <Conf />
    </div>
  )
}
