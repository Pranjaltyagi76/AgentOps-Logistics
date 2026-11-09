import { Plus } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { useAuth } from '@/app/auth/context'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { LockedBadge, StatusBadge } from '@/features/scenarios/badges'
import { toApiError } from '@/lib/api'

import { useAgents, useProviders } from './api'
import { ProviderBadge, ProviderStatusCards } from './components'

export function AgentListPage() {
  const { isOwner } = useAuth()
  const navigate = useNavigate()
  const [includeArchived, setIncludeArchived] = useState(false)
  const agents = useAgents(includeArchived)
  const providers = useProviders()

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Agents</h1>
          <p className="text-sm text-muted-foreground">
            Versioned agent configurations: provider, model, prompt, tools and limits.
          </p>
        </div>
        {isOwner ? (
          <Button size="sm" asChild>
            <Link to="/agents/new">
              <Plus aria-hidden /> New agent
            </Link>
          </Button>
        ) : null}
      </header>

      {providers.data ? <ProviderStatusCards providers={providers.data} /> : null}

      <div className="flex items-center gap-2">
        <Checkbox
          id="archived"
          checked={includeArchived}
          onCheckedChange={(v) => setIncludeArchived(v === true)}
        />
        <Label htmlFor="archived" className="text-sm font-normal">Show archived</Label>
      </div>

      {agents.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load agents</AlertTitle>
          <AlertDescription>{toApiError(agents.error).message}</AlertDescription>
        </Alert>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Agent</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Model / profile</TableHead>
                <TableHead className="text-right">Tools</TableHead>
                <TableHead className="text-right">Version</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {agents.isPending
                ? Array.from({ length: 2 }, (_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={6}><Skeleton className="h-8 w-full" /></TableCell>
                    </TableRow>
                  ))
                : agents.data.map((agent) => (
                    <TableRow key={agent.id} className="cursor-pointer" onClick={() => navigate(`/agents/${agent.id}`)}>
                      <TableCell className="max-w-md">
                        <Link
                          to={`/agents/${agent.id}`}
                          className="font-mono font-medium hover:underline"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {agent.name}
                        </Link>
                        <p className="line-clamp-2 text-xs text-muted-foreground">{agent.description}</p>
                      </TableCell>
                      <TableCell><ProviderBadge provider={agent.provider} /></TableCell>
                      <TableCell className="font-mono text-xs">{agent.model_id}</TableCell>
                      <TableCell className="text-right tabular-nums">{agent.tool_count}</TableCell>
                      <TableCell className="text-right tabular-nums">v{agent.version}</TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          <StatusBadge status={agent.status} />
                          {agent.is_locked ? <LockedBadge /> : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
              {agents.data && agents.data.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                    No agents yet. Seed the database to add the rule-based baselines.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
