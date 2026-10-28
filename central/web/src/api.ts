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
// kept = 이번 수집은 repo GitLab 에 접속이 안 돼 지난 수집 값을 이어 씀
export type RepoInfo = { project?: string | null; read?: boolean; missing?: boolean; kept?: boolean; build?: RepoBuild[]; code?: CodeVersions | null }

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
  trigger?: 'user' | 'auto' // 버튼(수동) | 매일 정해 둔 시각(자동)
}
export type CollectStatus = {
  request: CollectRequest | null
  // schedule = 자동 수집 시각(예: '09:00 Asia/Seoul'), 없으면 버튼만
  collector: { name: string; mode?: string | null; schedule?: string | null; last_seen_at?: string | null; alive: boolean } | null
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

// 서버 상태 — 서버가 스스로 적는 상태 파일(IdP 서버 status.json)을 수집기가 읽어 올린 것. 판정은 중앙이 지금 시각으로
// ok = 정상(초록) · alert = 경보(빨강: 문제 · 못 본 것 · 기록 멈춤) · unknown = 모름(회색: 못 읽음 · 수집기 멈춤)
export type HostStatus = {
  source: string // idp …
  state: 'ok' | 'alert' | 'unknown'
  reasons: string[] // 판정 이유(기록 멈춤 · 못 읽음 · 수집기 멈춤 …)
  host?: string | null
  problems: string[] // 확인된 문제
  unread: string[] // 보려고 했는데 못 본 것 — 비어 있어야 정상
  written_at?: string | null
  written_age_seconds?: number | null
  received_at?: string | null
  read_error?: string | null
}

export async function fetchHostStatus(): Promise<HostStatus[]> {
  const res = await fetch('/api/host-status')
  if (!res.ok) throw new Error(`GET /api/host-status ${res.status}`)
  return res.json()
}

// ── 서버 탭 '누가 · 어디로' — 금고의 gw · 서버 목록 (보기 전용) ──
// 이름표(Authentik 의 server-admin · developer 목록 — IdP 서버가 5분마다 적음) 상태. ok 가 아니면 이름을 안 붙임(이메일만)
export type NamesState = 'ok' | 'off' | 'unknown'
export type AccessMember = { name: string | null; email: string | null; active: boolean }
export type AccessPerson = {
  email: string // 운영자 줄은 'server-admin 그룹 전원'(줄 이름) — 실제 사람은 members
  role: 'admin' | 'developer'
  gw_account: string
  server_account: string
  note?: string
  name?: string | null // 개발자 — 이름표에서 찾은 이름(못 찾으면 null)
  active?: boolean | null // 개발자 — false = Authentik 에서 막힌 계정
  members?: AccessMember[] // 운영자 줄 — 이름표가 ok 일 때만 차고(활성 먼저), 모르면 빈 목록
  names_note?: string | null // 운영자 줄 — '이름 모름(이름표를 못 읽음)' 같은 짧은 알림
  where: { env: string; service: string }[]
}
export type AccessService = {
  name: string
  gw: { host: string; port: number } | null
  servers: { name: string; addr: string }[]
  developers: string[]
}
export type AccessEnv = { env: string; audience: string; services: AccessService[] }
export type Access = {
  state: 'ok' | 'off' | 'error' | 'denied' | 'no_identity' // no_identity = 로그인 정보(그룹)를 몰라 막음
  error?: string
  viewer: { email: string | null; role: string }
  envs: AccessEnv[]
  people: AccessPerson[]
  can_edit?: boolean // 목록 고치기를 보일까 — CT_INVENTORY_EDIT 가 켜졌고 운영자일 때만 true
  names?: { state: NamesState; reasons: string[] }
}

// 지금 로그인한 사람 — 그룹을 아는 모드(oidc · proxy)에서만 authenticated · groups 가 찬다
export type Me = { authenticated: boolean; email: string | null; groups: string[] }

export async function fetchMe(): Promise<Me> {
  const res = await fetch('/api/me')
  if (!res.ok) throw new Error(`GET /api/me ${res.status}`)
  return res.json()
}

// 개발자(server-admin 아님)는 서버 탭만 — API 도 같은 선으로 막는다(central/api/app/main.py)
export function developerOnly(me: Me | null): boolean {
  const groups = me && Array.isArray(me.groups) ? me.groups : []
  return !!me && me.authenticated === true && groups.includes('developer') && !groups.includes('server-admin')
}

export async function fetchAccess(): Promise<Access> {
  const res = await fetch('/api/access')
  if (!res.ok) throw new Error(`GET /api/access ${res.status}`)
  return res.json()
}

// ── 목록 고치기(운영자) — 금고 한 항목의 gw · 서버. users 는 여기서 안 고침(gw 의 idp-login user add 가 OS 계정도 만듦) ──
export type InventoryEntry = {
  env: string
  service: string
  version: number // 고치기 시작할 때의 판 — 저장할 때 이 판 그대로여야 쓴다(check-and-set)
  updated_at: string | null // 금고가 그 판에 적은 시각
  last_edit: { here: boolean; by: string | null; at: string | null } // here=false → 지금 판은 CT 밖(idp-login 등)에서 씀
  gw: { host: string; port: number } | null
  servers: Record<string, string>
  users_count: number
}
export type InventoryChange = {
  kind: 'gw_host' | 'gw_port' | 'server_add' | 'server_remove' | 'server_addr' | 'server_rename'
  name?: string
  from?: string | number | null
  to?: string | number | null
  addr?: string
}
export type InventoryEdit = { version: number; gw: { host: string; port: number } | null; servers: Record<string, string> }
export type InventorySaved = { saved: true; version: number; updated_at: string | null; changes: InventoryChange[]; history_error?: string }

// 상태 코드를 같이 — 409(다른 곳에서 먼저 고침) · 502(금고 거절 · 저장됐는지 모름)를 화면이 나눠 보인다
// why = 서버가 할 일(message)과 따로 준 원래 까닭(예: 금고 답 'permission denied') — 작은 줄로
export class ApiError extends Error {
  constructor(public status: number, message: string, public why?: string) {
    super(message)
  }
}

async function inventoryCall<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const detail = ((await res.json().catch(() => null)) as { detail?: unknown } | null)?.detail
    if (typeof detail === 'string') throw new ApiError(res.status, detail)
    const d = detail as { message?: unknown; why?: unknown } | null | undefined
    if (d && typeof d.message === 'string') throw new ApiError(res.status, d.message, typeof d.why === 'string' ? d.why : undefined)
    throw new ApiError(res.status, `${init?.method ?? 'GET'} ${url} ${res.status}`)
  }
  return res.json()
}

const invUrl = (env: string, service: string) => `/api/inventory/${encodeURIComponent(env)}/${encodeURIComponent(service)}`
const jsonBody = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const fetchInventoryEntry = (env: string, service: string) => inventoryCall<InventoryEntry>(invUrl(env, service))
export const previewInventoryEdit = (env: string, service: string, body: InventoryEdit) =>
  inventoryCall<{ version: number; changes: InventoryChange[] }>(`${invUrl(env, service)}/preview`, jsonBody('POST', body))
export const saveInventoryEdit = (env: string, service: string, body: InventoryEdit) =>
  inventoryCall<InventorySaved>(invUrl(env, service), jsonBody('PUT', body))

// 접속 기록 — 금고가 인증서(도장)를 내준 기록(IdP 요약 파일 → 수집기 → 중앙). 운영자만(아니면 403)
export type AccessEvent = {
  at: string // ISO UTC — 금고는 나노초까지 적음(수집기가 마이크로초로 자름)
  kind: 'person' | 'machine' | 'other'
  who: string | null // 이메일 · 기계 신분 이름 · 없을 수 있음
  env: string
  account: string | null // ubuntu · appuser · 없으면 개인 gw 계정(*-gw 역할)
  role: string | null // 금고 역할(dev-ubuntu · stg-gw · dev-runner …)
  serial: string | null // 인증서 번호 — 10-28 오전 전 기록은 없음
  result: string // issued(발급) · denied(거부)
  reason: string | null
}
export type AccessLog = {
  state: 'ok' | 'off' | 'unknown' | 'no_identity'
  reasons: string[]
  notes: string[]
  written_at: string | null
  host: string | null
  window_days: number | null
  files_read: number | null
  lines_read: number | null
  written_age_seconds: number | null
  stale_after_seconds: number | null
  events: AccessEvent[]
  // '누가' 칸 이메일 옆 이름 — 키는 이메일(소문자). 이름표를 모르면 people 이 비어 이메일만
  names?: { state: NamesState; reasons: string[]; notes: string[]; people: Record<string, { name: string | null; active: boolean }> }
}

// 403(운영자 아님)은 따로 알아보게 — '못 불러옴' 과 다르다
export class ForbiddenError extends Error {}

export async function fetchAccessLog(): Promise<AccessLog> {
  const res = await fetch('/api/access-log')
  if (res.status === 403) throw new ForbiddenError(((await res.json().catch(() => null)) as { detail?: string } | null)?.detail ?? '운영자만 볼 수 있어요')
  if (!res.ok) throw new Error(`GET /api/access-log ${res.status}`)
  return res.json()
}

// 지금 도는 ControlTower 버전 — 반영할 때 CT_VERSION/CT_BUILD 를 넣는다. 안 넣으면 'dev'(화면은 '버전 모름')
export type AppVersion = { version: string; build: string; started_at?: string | null }

export async function fetchVersion(): Promise<AppVersion> {
  const res = await fetch('/api/version')
  if (!res.ok) throw new Error(`GET /api/version ${res.status}`)
  return res.json()
}
