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

// 작업이력 한 페이지(최신순) + 전체 건수(X-Total-Count)
export async function fetchAuditPage(limit: number, offset: number): Promise<{ rows: AuditRow[]; total: number }> {
  const res = await fetch(`/api/audit?limit=${limit}&offset=${offset}`)
  if (!res.ok) throw new Error(`GET /api/audit ${res.status}`)
  const rows = (await res.json()) as AuditRow[]
  const total = Number(res.headers.get('X-Total-Count') ?? rows.length)
  return { rows, total: Number.isFinite(total) ? total : rows.length }
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
// 러너 태그 하나와 그걸 쓰는 job 들(why = 어떻게 정했나, images = job → image:)
// default_image = job 로그로 본 러너 기본 이미지(image: 없이 도는 job 이 실제로 쓰는 것)
export type ExecutorGroup = {
  tag: string
  value: string
  guess: boolean
  why?: string
  jobs: string[]
  images?: Record<string, string>
  default_image?: string
  runner_name?: string // GitLab 에 등록된 러너 이름(job 로그로 확인했을 때)
}
export type ExecutorCell = {
  value: string
  guess: boolean
  tags?: string[]
  counts?: Record<string, number> // job 마다 섞여 있을 때 방식별 job 수
  groups?: ExecutorGroup[]
} | null

// 환경 하나의 마지막 빌드·배포 — tag 로 성공한 job(GitLab API). side = 어느 GitLab 의 job 인가
export type VersionCell = { version: string; tag: string; at?: string | null; job?: number | null; side?: 'repo' | 'center' }
export type Versions = { build: Record<string, VersionCell>; deploy: Record<string, VersionCell> }
// 코드에 적힌 버전(.nvmrc · package.json · pom.xml)
export type CodeVersions = { node?: string; node_from?: string; node_rule?: 'exact' | 'min'; nest?: string; java?: string; java_from?: string }
// repo 쪽 — 프로젝트 · CI 가 빌드에 쓰는 런타임 이미지 · 코드에 적힌 버전. read=false 면 repo CI 를 못 읽음,
// missing=true 면 repo 저장소가 없음(없어짐 — 대상 파일에 repo: false) → 안 읽음
// from='log' = shell 러너라 CI 에 이미지가 없어 build job 로그에서 읽음(guess = 같은 러너의 다른 job 로그에서 본 값)
export type RepoBuild = {
  runtime: string
  version?: string | null
  image?: string | null
  jobs: string[]
  from?: 'log'
  job?: number
  runner?: string | null
  guess?: boolean
}
export type RepoInfo = { project?: string | null; read?: boolean; missing?: boolean; build?: RepoBuild[]; code?: CodeVersions | null }

export type ShapeRow = {
  service: string
  group?: string | null
  type?: string | null
  host?: 'gitlab' | 'github' | null // 어디서 빌드하나
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
  versions?: Versions | null // 없으면 모름(API 로 안 읽음)
  repo?: RepoInfo | null
  collected_at?: string | null
}

// 서버 compose 를 어디서 읽었나 — ssh(서버에서 직접) / file(복사해 둔 사본) / gitlab
// via = 거친 게이트웨이, kept = 이번 수집은 GitLab 만이라 지난 수집 값을 이어 씀
export type ComposeSrc = { kind: 'ssh' | 'file' | 'gitlab' | 'unknown'; auto?: boolean; via?: string; note?: string | null; where?: string; kept?: boolean }

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
  code?: CodeVersions | null // 코드에 적힌 버전
  compose_src?: Record<string, ComposeSrc | null> // 환경별 서버 compose 를 어디서 읽었나
  compose_miss?: Record<string, { state: 'fail' | 'planned'; reason: string }> // 못 읽음(이유) / 위치만 찾음
  deploy_envs?: string[] // 이 폴더 서비스가 배포하는 환경(CI 기준) — 여기 없는 환경 칸은 '—'
  group?: string | null // 그룹(프로젝트 묶음) — 연결된 서비스의 group
  config_repo?: string // 어느 config repo 에서 왔나(GitLab 프로젝트)
  folder?: string // 역할 줄(예: jobs/manager)일 때 실제 config 폴더(예: jobs/web) — 같은 이미지를 역할별로 띄움
  merged_into?: string // 다른 폴더로 합쳐져 안 쓰는 폴더면 그 폴더(예: chat/was)
  compose?: Record<string, 'mount' | 'command' | 'image'> // start.sh 형태(서버 compose): shell(마운트) / compose(command:) / Dockerfile(이미지 CMD)
  collected_at?: string | null
}

export async function fetchConfig(): Promise<ConfigRow[]> {
  const res = await fetch('/api/cicd/config')
  if (!res.ok) throw new Error(`GET /api/cicd/config ${res.status}`)
  return res.json()
}

// 다시 수집 — 화면 버튼이 남긴 요청. 중앙은 키·토큰이 없어, ControlTower 서버의 수집기(runner agent)가 가져가 처리
export type CollectRequest = {
  id: number
  kind: string
  status: 'pending' | 'running' | 'done' | 'failed'
  requested_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  collector?: string | null
  message?: string | null
}
export type CollectStatus = {
  request: CollectRequest | null
  collector: { name: string; mode?: string | null; last_seen_at?: string | null; alive: boolean } | null
}

export async function fetchCollectStatus(kind = 'shape'): Promise<CollectStatus> {
  const res = await fetch(`/api/collect/status?kind=${encodeURIComponent(kind)}`)
  if (!res.ok) throw new Error(`GET /api/collect/status ${res.status}`)
  return res.json()
}

export async function requestCollect(kind = 'shape'): Promise<CollectRequest> {
  const res = await fetch('/api/collect/requests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind }),
  })
  if (!res.ok) throw new Error(`POST /api/collect/requests ${res.status}`)
  return res.json()
}

export async function fetchShapes(): Promise<ShapeRow[]> {
  const res = await fetch('/api/cicd/shape')
  if (!res.ok) throw new Error(`GET /api/cicd/shape ${res.status}`)
  return res.json()
}

