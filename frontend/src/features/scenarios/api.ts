import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { api } from '@/lib/api'

import type {
  ImportResponse,
  ScenarioDetail,
  ScenarioFilters,
  ScenarioPage,
  Taxonomy,
  ValidationReport,
  WriteResult,
} from './types'

const PAGE_SIZE = 25

export const scenarioKeys = {
  all: ['scenarios'] as const,
  list: (filters: ScenarioFilters) => ['scenarios', 'list', filters] as const,
  detail: (id: string) => ['scenarios', 'detail', id] as const,
  source: (id: string) => ['scenarios', 'source', id] as const,
}

export function useTaxonomy() {
  return useQuery({
    queryKey: ['taxonomy'],
    queryFn: async () => (await api.get<Taxonomy>('/taxonomy')).data,
    staleTime: Infinity,
  })
}

export function useScenarioList(filters: ScenarioFilters) {
  return useInfiniteQuery({
    queryKey: scenarioKeys.list(filters),
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const params = { ...filters, limit: PAGE_SIZE, cursor: pageParam ?? undefined }
      return (await api.get<ScenarioPage>('/scenarios', { params })).data
    },
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  })
}

export function useScenario(id: string, enabled = true) {
  return useQuery({
    queryKey: scenarioKeys.detail(id),
    queryFn: async () => (await api.get<ScenarioDetail>(`/scenarios/${id}`)).data,
    enabled: enabled && id !== '',
  })
}

/** The exact stored scenario JSON (owner only), used by the editor and export. */
export async function fetchScenarioSource(id: string): Promise<Record<string, unknown>> {
  return (await api.get<Record<string, unknown>>(`/scenarios/${id}/export`)).data
}

export function useScenarioSource(id: string, enabled = true) {
  return useQuery({
    queryKey: scenarioKeys.source(id),
    queryFn: () => fetchScenarioSource(id),
    enabled,
    staleTime: 0,
  })
}

export async function fetchAllScenarios(): Promise<{ scenarios: unknown[] }> {
  return (await api.get<{ scenarios: unknown[] }>('/scenarios/export')).data
}

export async function validateScenario(scenario: unknown): Promise<ValidationReport> {
  return (await api.post<ValidationReport>('/scenarios/validate', scenario)).data
}

function useInvalidatingMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: scenarioKeys.all }),
  })
}

export function useSaveScenario() {
  return useInvalidatingMutation(
    async (vars: { id?: string; scenario: unknown; status?: 'draft' | 'active' }) => {
      const body = { scenario: vars.scenario, status: vars.status }
      const response = vars.id
        ? await api.patch<WriteResult>(`/scenarios/${vars.id}`, body)
        : await api.post<WriteResult>('/scenarios', body)
      return response.data
    },
  )
}

export function useCloneScenario() {
  return useInvalidatingMutation(
    async (id: string) => (await api.post<WriteResult>(`/scenarios/${id}/clone`)).data,
  )
}

export function useSetScenarioArchived() {
  return useInvalidatingMutation(async (vars: { id: string; archived: boolean }) => {
    const action = vars.archived ? 'archive' : 'restore'
    return (await api.post(`/scenarios/${vars.id}/${action}`)).data
  })
}

export function useImportScenarios() {
  return useInvalidatingMutation(
    async (scenarios: unknown[]) =>
      (await api.post<ImportResponse>('/scenarios/import', { scenarios })).data,
  )
}
