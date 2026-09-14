export type Server = {
  id: number
  hostname: string
  ip?: string | null
  ssh_user: string
  access_control?: string | null
  credential_alias?: string | null
  status: string
  last_checked_at?: string | null
}

export async function fetchServers(): Promise<Server[]> {
  const res = await fetch('/api/servers')
  if (!res.ok) throw new Error(`GET /api/servers ${res.status}`)
  return res.json()
}

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
  server_id: number
  hostname: string
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
