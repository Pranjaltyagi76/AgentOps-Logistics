import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

import type { Comparison, Suite, SuiteIn, SuiteRun, SuiteRunDetail } from './types'

const POLL_MS = 2000
const isActive = (status?: string) => status === 'queued' || status === 'running'

export function useSuites() {
  return useQuery({
    queryKey: ['suites'],
    queryFn: async () => (await api.get<Suite[]>('/suites')).data,
  })
}

export function useSuite(id: string | undefined) {
  return useQuery({
    queryKey: ['suites', id],
    queryFn: async () => (await api.get<Suite>(`/suites/${id}`)).data,
    enabled: Boolean(id),
  })
}

export function useSaveSuite(id?: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: SuiteIn) =>
      (id ? await api.put<Suite>(`/suites/${id}`, body) : await api.post<Suite>('/suites', body)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['suites'] }),
  })
}

export function useSuiteRuns(params: { suiteId?: string; status?: string } = {}) {
  return useQuery({
    queryKey: ['suite-runs', params.suiteId ?? 'all', params.status ?? 'all'],
    queryFn: async () =>
      (await api.get<SuiteRun[]>('/suite-runs', { params: { suite_id: params.suiteId, status: params.status } })).data,
    refetchInterval: (query) => (query.state.data?.some((r) => isActive(r.status)) ? POLL_MS : false),
  })
}

export function useSuiteRun(id: string) {
  return useQuery({
    queryKey: ['suite-runs', 'detail', id],
    queryFn: async () => (await api.get<SuiteRunDetail>(`/suite-runs/${id}`)).data,
    refetchInterval: (query) => (isActive(query.state.data?.status) ? POLL_MS : false),
  })
}

export function useLaunchSuite(suiteId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (vars: { agentId: string; repeats: number }) =>
      (await api.post<SuiteRun>(`/suites/${suiteId}/runs`, { agent_config_id: vars.agentId, repeats: vars.repeats }))
        .data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['suite-runs'] }),
  })
}

export function useCancelSuiteRun(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.post<SuiteRun>(`/suite-runs/${id}/cancel`)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['suite-runs'] }),
  })
}

export function useComparison(baseline: string | null, candidate: string | null) {
  return useQuery({
    queryKey: ['comparisons', baseline, candidate],
    queryFn: async () =>
      (
        await api.get<Comparison>('/comparisons', {
          params: { baseline_suite_run_id: baseline, candidate_suite_run_id: candidate },
        })
      ).data,
    enabled: Boolean(baseline && candidate),
    retry: false,
  })
}
