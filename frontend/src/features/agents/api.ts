import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

import type { AgentConfig, AgentDetail, AgentSummary, AgentWriteResult, ProviderStatus } from './types'

export const agentKeys = {
  all: ['agents'] as const,
  list: (includeArchived: boolean) => ['agents', 'list', includeArchived] as const,
  detail: (id: string) => ['agents', 'detail', id] as const,
}

export function useAgents(includeArchived = false) {
  return useQuery({
    queryKey: agentKeys.list(includeArchived),
    queryFn: async () =>
      (await api.get<AgentSummary[]>('/agents', { params: { include_archived: includeArchived } })).data,
  })
}

export function useAgent(id: string, enabled = true) {
  return useQuery({
    queryKey: agentKeys.detail(id),
    queryFn: async () => (await api.get<AgentDetail>(`/agents/${id}`)).data,
    enabled: enabled && id !== '',
  })
}

export function useProviders() {
  return useQuery({
    queryKey: ['agents', 'providers'],
    queryFn: async () => (await api.get<ProviderStatus[]>('/agents/providers')).data,
    staleTime: 60_000,
  })
}

export function useToolNames() {
  return useQuery({
    queryKey: ['agents', 'tools'],
    queryFn: async () => (await api.get<string[]>('/agents/tools')).data,
    staleTime: Infinity,
  })
}

export async function validateAgent(config: Partial<AgentConfig>) {
  return (await api.post<{ valid: boolean; errors: { loc: string; msg: string }[] }>('/agents/validate', config))
    .data
}

function useInvalidating<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: agentKeys.all }),
  })
}

export function useSaveAgent() {
  return useInvalidating(async (vars: { id?: string; config: Partial<AgentConfig> }) => {
    const response = vars.id
      ? await api.patch<AgentWriteResult>(`/agents/${vars.id}`, vars.config)
      : await api.post<AgentWriteResult>('/agents', vars.config)
    return response.data
  })
}

export function useCloneAgent() {
  return useInvalidating(async (id: string) => (await api.post<AgentWriteResult>(`/agents/${id}/clone`)).data)
}

export function useSetAgentArchived() {
  return useInvalidating(async (vars: { id: string; archived: boolean }) =>
    (await api.post(`/agents/${vars.id}/${vars.archived ? 'archive' : 'restore'}`)).data,
  )
}
