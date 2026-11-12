import { Play } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

import { useAuth } from '@/app/auth/context'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useAgents, useProviders } from '@/features/agents/api'
import type { ProviderStatus } from '@/features/agents/types'
import { useScenarioList } from '@/features/scenarios/api'
import { toApiError } from '@/lib/api'

import { useLaunchRun } from './api'

export function RunLauncherPage() {
  const { isOwner } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const agents = useAgents()
  const providers = useProviders()
  const scenarios = useScenarioList({ status: 'active' })
  const launch = useLaunchRun()
  const [scenarioId, setScenarioId] = useState(params.get('scenario') ?? '')
  const [agentId, setAgentId] = useState(params.get('agent') ?? '')
  const [error, setError] = useState<string | null>(null)

  const status = new Map<string, ProviderStatus>((providers.data ?? []).map((p) => [p.provider, p]))
  /** Why an agent can't be launched by this user right now, or null if it can. */
  function blockedReason(provider: string): string | null {
    if (provider === 'rule_based') return null
    const p = status.get(provider)
    if (!isOwner) return 'owner only'
    if (!p?.configured) return 'not configured'
    if (!p.available) return 'not available yet'
    if (p.runs_left_today === 0) return 'daily limit reached'
    return null
  }
  const selectedAgent = agents.data?.find((a) => a.id === agentId)
  const selectedLlm = selectedAgent && selectedAgent.provider !== 'rule_based' ? status.get(selectedAgent.provider) : undefined
  const scenarioRows = scenarios.data?.pages.flatMap((p) => p.items) ?? []

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      const run = await launch.mutateAsync({ scenarioId, agentId })
      navigate(`/runs/${run.id}`)
    } catch (err) {
      setError(toApiError(err).message)
    }
  }

  if (agents.isPending || scenarios.isPending) return <Skeleton className="h-64 w-full" />

  return (
    <form onSubmit={(e) => void onSubmit(e)} className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">New run</h1>
        <p className="text-sm text-muted-foreground">
          Run one agent configuration against one scenario. The run executes in the background and its trace appears live.
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">What to run</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="agent">Agent</Label>
            <Select value={agentId} onValueChange={setAgentId}>
              <SelectTrigger id="agent"><SelectValue placeholder="Choose an agent" /></SelectTrigger>
              <SelectContent>
                {(agents.data ?? []).map((agent) => {
                  const blocked = blockedReason(agent.provider)
                  return (
                    <SelectItem key={agent.id} value={agent.id} disabled={blocked !== null}>
                      {agent.name} v{agent.version}
                      {blocked ? ` (${blocked})` : ''}
                    </SelectItem>
                  )
                })}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="scenario">Scenario</Label>
            <Select value={scenarioId} onValueChange={setScenarioId}>
              <SelectTrigger id="scenario"><SelectValue placeholder="Choose a scenario" /></SelectTrigger>
              <SelectContent>
                {scenarioRows.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.scenario_key} v{s.version}: {s.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <p className="text-xs text-muted-foreground">
            Limits come from the agent config (max steps, tool calls and time). At most a few runs execute at once; others wait in the queue.
            {isOwner ? '' : ' Demo viewers can run the rule-based agents.'}
          </p>
          {selectedLlm ? (
            <p className="text-xs text-muted-foreground" data-testid="llm-quota">
              Uses the free {selectedLlm.label} quota{selectedLlm.model ? ` (${selectedLlm.model})` : ''}:{' '}
              {selectedLlm.runs_left_today ?? '?'} of {selectedLlm.daily_cap ?? '?'} LLM runs left today.
            </p>
          ) : null}
        </CardContent>
      </Card>

      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <Button type="submit" className="self-start" disabled={!agentId || !scenarioId || launch.isPending}>
        <Play aria-hidden /> {launch.isPending ? 'Starting…' : 'Launch run'}
      </Button>
    </form>
  )
}
