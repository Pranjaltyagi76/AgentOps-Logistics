import { Archive, ArchiveRestore, ArrowLeft, Copy, Download, EyeOff, Pencil } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'

import { useAuth } from '@/app/auth/context'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { toApiError } from '@/lib/api'
import { downloadJson } from '@/lib/download'
import { formatDateTime, humanize } from '@/lib/format'
import { cn } from '@/lib/utils'

import {
  fetchScenarioSource,
  useCloneScenario,
  useScenario,
  useSetScenarioArchived,
  useTaxonomy,
} from './api'
import { CategoryBadge, DifficultyBadge, LockedBadge, StatusBadge } from './badges'
import { GroundTruthView } from './GroundTruthView'
import { MockDataView } from './MockDataView'

export interface DetailNotice {
  notice?: string
}

export function ScenarioDetailPage() {
  const { id = '' } = useParams()
  const { isOwner } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const notice = (location.state as DetailNotice | null)?.notice

  const scenario = useScenario(id)
  const taxonomy = useTaxonomy()
  const clone = useCloneScenario()
  const archive = useSetScenarioArchived()
  const [error, setError] = useState<string | null>(null)

  if (scenario.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (scenario.isError) {
    const err = toApiError(scenario.error)
    return (
      <Alert variant="destructive">
        <AlertTitle>{err.status === 404 ? 'Scenario not found' : 'Could not load scenario'}</AlertTitle>
        <AlertDescription>
          {err.message} <Link to="/scenarios" className="underline">Back to scenarios</Link>
        </AlertDescription>
      </Alert>
    )
  }

  const s = scenario.data
  const v = s.visible
  const gatedTools = new Set(taxonomy.data?.tools.filter((t) => t.policy_gated).map((t) => t.name))
  const archived = s.status === 'archived'

  async function run(action: () => Promise<void>) {
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(toApiError(err).message)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Link to="/scenarios" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> Scenarios
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">{s.title}</h1>
          <p className="font-mono text-sm text-muted-foreground">{s.scenario_key} · v{s.version}</p>
          <div className="flex flex-wrap gap-1.5">
            <CategoryBadge category={s.category} />
            <DifficultyBadge difficulty={s.difficulty} />
            <StatusBadge status={s.status} />
            {s.is_locked ? <LockedBadge /> : null}
          </div>
        </div>
        {isOwner ? (
          <div className="flex flex-wrap gap-2">
            {s.can_edit ? (
              <Button size="sm" asChild>
                <Link to={`/scenarios/${s.id}/edit`}><Pencil aria-hidden /> Edit</Link>
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="outline"
              disabled={clone.isPending}
              onClick={() =>
                void run(async () => {
                  const result = await clone.mutateAsync(s.id)
                  navigate(`/scenarios/${result.scenario.id}`, {
                    state: { notice: `Cloned as ${result.scenario.scenario_key} (draft).` } satisfies DetailNotice,
                  })
                })
              }
            >
              <Copy aria-hidden /> Clone
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                void run(async () => {
                  downloadJson(`${s.scenario_key}.v${s.version}.json`, await fetchScenarioSource(s.id))
                })
              }
            >
              <Download aria-hidden /> Export
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={archive.isPending}
              onClick={() => void run(async () => { await archive.mutateAsync({ id: s.id, archived: !archived }) })}
            >
              {archived ? <ArchiveRestore aria-hidden /> : <Archive aria-hidden />}
              {archived ? 'Restore' : 'Archive'}
            </Button>
          </div>
        ) : null}
      </header>

      {notice ? (
        <Alert>
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      ) : null}
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {s.versions.length > 1 ? (
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="text-muted-foreground">Versions:</span>
          {s.versions.map((version) => (
            <Link
              key={version.id}
              to={`/scenarios/${version.id}`}
              className={cn(
                'rounded border px-2 py-0.5 tabular-nums',
                version.id === s.id ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-accent',
              )}
            >
              v{version.version}
            </Link>
          ))}
        </div>
      ) : null}

      <Tabs defaultValue="customer">
        <TabsList>
          <TabsTrigger value="customer">Customer view</TabsTrigger>
          <TabsTrigger value="data">Mock data</TabsTrigger>
          <TabsTrigger value="truth">Ground truth</TabsTrigger>
          <TabsTrigger value="json">JSON</TabsTrigger>
        </TabsList>

        <TabsContent value="customer" className="mt-4 flex flex-col gap-4">
          <p className="max-w-3xl text-sm text-muted-foreground">{v.description}</p>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Customer message</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <blockquote className="rounded-lg bg-muted px-4 py-3">{v.customer_message}</blockquote>
              <p className="text-xs text-muted-foreground">Simulated “now”: {formatDateTime(v.as_of)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">What the agent receives</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-[12rem_1fr]">
                <dt className="text-muted-foreground">Visible context</dt>
                <dd className="flex flex-wrap gap-1">
                  {Object.entries(v.visible_context).map(([key, value]) => (
                    <Badge key={key} variant="outline" className="font-mono">{key}: {value}</Badge>
                  ))}
                </dd>
                <dt className="text-muted-foreground">Available tools</dt>
                <dd className="flex flex-wrap gap-1">
                  {v.available_tools.map((tool) => (
                    <Badge
                      key={tool}
                      variant="outline"
                      className={cn('font-mono', gatedTools.has(tool) && 'border-destructive/50 text-destructive')}
                      title={gatedTools.has(tool) ? 'Policy-gated: blocked unless explicitly authorised' : undefined}
                    >
                      {tool}
                    </Badge>
                  ))}
                </dd>
                <dt className="text-muted-foreground">Permitted SOPs</dt>
                <dd className="flex flex-wrap gap-1">
                  {v.permitted_documents.length
                    ? v.permitted_documents.map((doc) => <Badge key={doc} variant="secondary">{humanize(doc)}</Badge>)
                    : <span className="text-muted-foreground">None</span>}
                </dd>
              </dl>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="data" className="mt-4">
          <MockDataView data={v.mock_data} asOf={v.as_of} />
        </TabsContent>

        <TabsContent value="truth" className="mt-4">
          {s.hidden ? (
            <GroundTruthView hidden={s.hidden} taxonomy={taxonomy.data} />
          ) : (
            <Alert>
              <EyeOff aria-hidden />
              <AlertTitle>Hidden for demo viewers</AlertTitle>
              <AlertDescription>
                The expected root cause, required evidence and scoring rules are visible only to the
                owner, the same way the agent under test never sees them.
              </AlertDescription>
            </Alert>
          )}
        </TabsContent>

        <TabsContent value="json" className="mt-4">
          <pre className="max-h-[70vh] overflow-auto rounded-lg border bg-muted/40 p-4 text-xs">
            {JSON.stringify(s.hidden ? { ...v, ...s.hidden } : v, null, 2)}
          </pre>
        </TabsContent>
      </Tabs>

      <p className="text-xs text-muted-foreground">
        Created {formatDateTime(s.created_at)} · updated {formatDateTime(s.updated_at)}
      </p>
    </div>
  )
}
