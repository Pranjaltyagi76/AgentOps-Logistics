import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

import {
  ACTIVE_STATUSES,
  type Evaluation,
  type FailureReport,
  type RunDetail,
  type RunPage,
  type RunStatus,
  type Trace,
} from './types'

/** Poll fast while a run is queued/running; stop once it reaches a final state. */
const ACTIVE_POLL_MS = 1500

export const runKeys = {
  all: ['runs'] as const,
  list: (status?: string) => ['runs', 'list', status ?? 'all'] as const,
  detail: (id: string) => ['runs', 'detail', id] as const,
  trace: (id: string) => ['runs', 'trace', id] as const,
}

export const isActive = (status: RunStatus | undefined) =>
  status !== undefined && ACTIVE_STATUSES.includes(status)

export function useRuns(status?: string) {
  return useInfiniteQuery({
    queryKey: runKeys.list(status),
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (await api.get<RunPage>('/runs', { params: { status, limit: 25, cursor: pageParam ?? undefined } })).data,
    getNextPageParam: (last) => last.next_cursor,
    // Refresh while anything on the first page is still in flight.
    refetchInterval: (query) =>
      query.state.data?.pages[0]?.items.some((r) => isActive(r.status)) ? 3000 : false,
  })
}

export function useRun(id: string) {
  return useQuery({
    queryKey: runKeys.detail(id),
    queryFn: async () => (await api.get<RunDetail>(`/runs/${id}`)).data,
    refetchInterval: (query) => (isActive(query.state.data?.status) ? ACTIVE_POLL_MS : false),
  })
}

export function useTrace(id: string, active: boolean) {
  return useQuery({
    queryKey: runKeys.trace(id),
    queryFn: async () => (await api.get<Trace>(`/runs/${id}/trace`)).data,
    refetchInterval: active ? ACTIVE_POLL_MS : false,
  })
}

export function useLaunchRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (vars: { scenarioId: string; agentId: string }) =>
      (await api.post<RunDetail>('/runs', { scenario_id: vars.scenarioId, agent_config_id: vars.agentId })).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: runKeys.all }),
  })
}

export function useCancelRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => (await api.post<RunDetail>(`/runs/${id}/cancel`)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: runKeys.all }),
  })
}

/** Available once a run has finished (cancelled runs are not scored). */
export function useEvaluation(id: string, finished: boolean) {
  return useQuery({
    queryKey: ['runs', 'evaluation', id],
    queryFn: async () => (await api.get<Evaluation>(`/runs/${id}/evaluation`)).data,
    enabled: finished,
    retry: false,
  })
}

/** Failure report for the run's latest evaluation (same availability as the evaluation). */
export function useFailureReport(id: string, finished: boolean) {
  return useQuery({
    queryKey: ['runs', 'failure-report', id],
    queryFn: async () => (await api.get<FailureReport>(`/runs/${id}/failure-report`)).data,
    enabled: finished,
    retry: false,
  })
}

/** Owner: run the advisory LLM judge on a scored run. */
export function useRunJudge(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.post<Evaluation>(`/runs/${id}/judge`)).data,
    onSuccess: (evaluation) => queryClient.setQueryData(['runs', 'evaluation', id], evaluation),
  })
}
