export type Server = {
  id: number
  hostname: string
  ip?: string | null
  ssh_user: string
  access_control?: string | null
  credential_alias?: string | null
  status: string
}

export async function fetchServers(): Promise<Server[]> {
  const res = await fetch('/api/servers')
  if (!res.ok) throw new Error(`GET /api/servers ${res.status}`)
  return res.json()
}
