import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

// Hand-written for Phase 0; replaced by types generated from /openapi.json later.
export interface HealthResponse {
  status: 'ok'
  db: 'ok'
}

export interface VersionResponse {
  name: string
  version: string
  git_sha: string
  environment: string
}

export async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await api.get<HealthResponse>('/health')
  return data
}

export async function fetchVersion(): Promise<VersionResponse> {
  const { data } = await api.get<VersionResponse>('/version')
  return data
}

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 15_000,
    retry: false,
  })
}

export function useVersion() {
  return useQuery({ queryKey: ['version'], queryFn: fetchVersion, retry: false })
}
