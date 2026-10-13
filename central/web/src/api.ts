export type Server = {
  id: number
  hostname: string
  ip?: string | null
  ssh_user: string
  access_control?: string | null
  credential_alias?: string | null
  group_id?: number | null
  group?: string | null
  tags?: string[]
  needs_2fa?: boolean | null
  status: string
  last_checked_at?: string | null
}

export async function fetchServers(): Promise<Server[]> {
  const res = await fetch('/api/servers')
  if (!res.ok) throw new Error(`GET /api/servers ${res.status}`)
  return res.json()
}

export type Group = { id: number; name: string; count: number }

export async function fetchGroups(): Promise<Group[]> {
  const res = await fetch('/api/groups')
  if (!res.ok) throw new Error(`GET /api/groups ${res.status}`)
  return res.json()
}

async function postJsonServer(url: string, body: unknown): Promise<unknown> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail
    } catch {
      /* noop */
    }
    throw new Error(detail)
  }
  return res.json()
}

export const createGroup = (name: string) => postJsonServer('/api/groups', { name }) as Promise<Group>
export const setServerMeta = (id: number, meta: { group_id?: number | null; tags?: string[] }) =>
  postJsonServer(`/api/servers/${id}/meta`, meta) as Promise<Server>

export type ConfStatus = 'synced' | 'drift' | 'no_baseline' | 'error'

export type ConfRow = {
  server_id: number
  hostname: string
  path: string
  status: ConfStatus
  detail?: string
  collected_at?: string | null
}

export async function fetchConf(): Promise<ConfRow[]> {
  const res = await fetch('/api/conf')
  if (!res.ok) throw new Error(`GET /api/conf ${res.status}`)
  return res.json()
}

export type ApplyStatus = 'pending' | 'approved' | 'applied' | 'failed' | 'canceled' | 'rolled_back'

export type ApplyIntent = {
  id: number
  server_id: number
  hostname: string
  path: string
  status: ApplyStatus
  from_sha?: string | null
  to_sha?: string | null
  diff?: string | null
  requested_by?: string | null
  approved_by?: string | null
  error?: string | null
  created_at?: string | null
  approved_at?: string | null
  applied_at?: string | null
}

async function postJson(url: string, body?: unknown): Promise<ApplyIntent> {
  const res = await fetch(url, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* noop */
    }
    throw new Error(detail)
  }
  return res.json()
}

export async function fetchApplyIntents(): Promise<ApplyIntent[]> {
  const res = await fetch('/api/conf/apply')
  if (!res.ok) throw new Error(`GET /api/conf/apply ${res.status}`)
  return res.json()
}

export async function fetchConfTargets(): Promise<string[]> {
  const res = await fetch('/api/conf/targets')
  if (!res.ok) throw new Error(`GET /api/conf/targets ${res.status}`)
  return res.json()
}

export const addConfTarget = (path: string) => postJsonServer('/api/conf/targets', { path })

export const planApply = (server_id: number, path: string) =>
  postJson('/api/conf/apply/plan', { server_id, path })
export const approveApply = (id: number) => postJson(`/api/conf/apply/${id}/approve`)
export const cancelApply = (id: number) => postJson(`/api/conf/apply/${id}/cancel`)

export type UpdatePkg = { name: string; from: string; to: string; security: boolean }

export type UpdateRow = {
  server_id: number
  hostname: string
  pending: number
  security: number
  packages: UpdatePkg[]
  error?: string
  collected_at?: string | null
}

export async function fetchUpdates(): Promise<UpdateRow[]> {
  const res = await fetch('/api/updates')
  if (!res.ok) throw new Error(`GET /api/updates ${res.status}`)
  return res.json()
}

export type AuditRow = {
  id: number
  actor: string
  action: string
  target_type?: string | null
  target_id?: string | null
  detail?: string | null
  created_at?: string | null
}

export async function fetchAudit(): Promise<AuditRow[]> {
  const res = await fetch('/api/audit')
  if (!res.ok) throw new Error(`GET /api/audit ${res.status}`)
  return res.json()
}

export type VersionRow = {
  kind: 'server' | 'repo'
  name: string
  tools: Record<string, string>
  collected_at?: string | null
}

export async function fetchVersions(): Promise<VersionRow[]> {
  const res = await fetch('/api/versions')
  if (!res.ok) throw new Error(`GET /api/versions ${res.status}`)
  return res.json()
}

// 서비스 비교표 — 러너가 .gitlab-ci.yml·compose 를 읽어 만든 한 행
export type DeployCell = { path: 'direct' | 'image' | 'build'; by?: 'repo' | 'center' | 'compose'; manual: boolean | null; mismatch?: boolean }
export type ExecutorGroup = { tag: string; value: string; guess: boolean; jobs: string[] } // 러너 태그 하나와 그걸 쓰는 job 들
export type ExecutorCell = {
  value: string
  guess: boolean
  tags?: string[]
  counts?: Record<string, number> // job 마다 섞여 있을 때 방식별 job 수
  groups?: ExecutorGroup[]
} | null

export type ShapeRow = {
  service: string
  group?: string | null
  type?: string | null
  note?: string | null
  runtime?: string | null
  runtime_version?: string | null
  base_image?: string | null
  base_tag?: string | null
  deploy?: Record<string, DeployCell>
  executor_repo?: ExecutorCell
  executor_center?: ExecutorCell
  startup?: boolean | null
  start_state?: 'legacy' | 'leftover' | 'server' | 'done' | 'base' | 'none' | null // config 폴더 기준(연결된 경우)
  env_keys?: number | null
  env_changed_at?: string | null
  collected_at?: string | null
}

// 서버 compose 를 어디서 읽었나 — ssh(서버에서 직접) / file(복사해 둔 사본) / gitlab
export type ComposeSrc = { kind: 'ssh' | 'file' | 'gitlab' | 'unknown'; auto?: boolean; note?: string | null; where?: string }

// center config repo 폴더 하나(<서비스>/<타입>)
export type ConfigRow = {
  path: string
  runtime?: string | null
  runtime_version?: string | null
  base_image?: string | null
  base_tag?: string | null
  start?: 'dockerfile' | 'start.sh' | 'server' | 'base' | null // 처음 실행할 명령(이미지 기준)
  start_files?: string[]
  state: 'legacy' | 'leftover' | 'server' | 'done' | 'base' | 'none' // 정리할 것
  code?: { node?: string; node_from?: string; node_rule?: 'exact' | 'min'; nest?: string; java?: string } | null // 코드에 적힌 버전
  compose_src?: Record<string, ComposeSrc | null> // 환경별 서버 compose 를 어디서 읽었나
  compose?: Record<string, 'mount' | 'command' | 'image'> // start.sh 형태(서버 compose): shell(마운트) / compose(command:) / Dockerfile(이미지 CMD)
  collected_at?: string | null
}

export async function fetchConfig(): Promise<ConfigRow[]> {
  const res = await fetch('/api/cicd/config')
  if (!res.ok) throw new Error(`GET /api/cicd/config ${res.status}`)
  return res.json()
}

export async function fetchShapes(): Promise<ShapeRow[]> {
  const res = await fetch('/api/cicd/shape')
  if (!res.ok) throw new Error(`GET /api/cicd/shape ${res.status}`)
  return res.json()
}

