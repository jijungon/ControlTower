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

export type CicdRow = {
  service: string
  project?: string | null
  has_cicd: boolean
  status?: string | null
  ref?: string | null
  sha?: string | null
  web_url?: string | null
  collected_at?: string | null
}

export async function fetchCicd(): Promise<CicdRow[]> {
  const res = await fetch('/api/cicd')
  if (!res.ok) throw new Error(`GET /api/cicd ${res.status}`)
  return res.json()
}

export const addCicdTarget = (service: string, project: string) =>
  postJsonServer('/api/cicd/targets', { service, project })

export type RepoTarget = { repo: string; project: string }

export async function fetchRepoTargets(): Promise<RepoTarget[]> {
  const res = await fetch('/api/versions/repo-targets')
  if (!res.ok) throw new Error(`GET /api/versions/repo-targets ${res.status}`)
  return res.json()
}

export const addRepoTarget = (repo: string, project: string) =>
  postJsonServer('/api/versions/repo-targets', { repo, project })
