import { Download, FilePlus2, Search, Upload, X } from 'lucide-react'
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { useAuth } from '@/app/auth/context'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { toApiError } from '@/lib/api'
import { downloadJson } from '@/lib/download'
import { humanize } from '@/lib/format'

import { fetchAllScenarios, useImportScenarios, useScenarioList, useTaxonomy } from './api'
import { CategoryBadge, DifficultyBadge, LockedBadge, StatusBadge } from './badges'
import type { ImportResponse, ScenarioFilters } from './types'

const ALL = '__all__'
const FILTER_KEYS = ['q', 'category', 'difficulty', 'status', 'tag'] as const

function FilterSelect(props: {
  label: string
  value: string | undefined
  options: string[]
  onChange: (value: string | undefined) => void
}) {
  return (
    <Select value={props.value ?? ALL} onValueChange={(v) => props.onChange(v === ALL ? undefined : v)}>
      <SelectTrigger className="w-44" aria-label={props.label}>
        <SelectValue placeholder={props.label} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>All {props.label.toLowerCase()}</SelectItem>
        {props.options.map((option) => (
          <SelectItem key={option} value={option}>
            {humanize(option)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/** Accepts a single scenario, an array, or an export file ({"scenarios": [...]}). */
function toScenarioList(parsed: unknown): unknown[] {
  if (Array.isArray(parsed)) return parsed
  if (parsed && typeof parsed === 'object' && Array.isArray((parsed as { scenarios?: unknown }).scenarios)) {
    return (parsed as { scenarios: unknown[] }).scenarios
  }
  return [parsed]
}

export function ScenarioListPage() {
  const { isOwner } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const filters: ScenarioFilters = Object.fromEntries(
    FILTER_KEYS.flatMap((key) => (params.get(key) ? [[key, params.get(key)!]] : [])),
  )

  const [search, setSearch] = useState(filters.q ?? '')
  const setFilter = (key: keyof ScenarioFilters, value: string | undefined) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      if (value) next.set(key, value)
      else next.delete(key)
      return next
    }, { replace: true })
  }
  // Debounce free-text search so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      if ((filters.q ?? '') !== search.trim()) setFilter('q', search.trim() || undefined)
    }, 300)
    return () => window.clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  const taxonomy = useTaxonomy()
  const list = useScenarioList(filters)
  const rows = list.data?.pages.flatMap((page) => page.items) ?? []
  const total = list.data?.pages[0]?.total
  const hasFilters = FILTER_KEYS.some((key) => params.get(key))

  const importer = useImportScenarios()
  const fileInput = useRef<HTMLInputElement>(null)
  const [importResult, setImportResult] = useState<ImportResponse | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  async function onImportFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setActionError(null)
    setImportResult(null)
    try {
      const scenarios = toScenarioList(JSON.parse(await file.text()))
      setImportResult(await importer.mutateAsync(scenarios))
    } catch (err) {
      setActionError(err instanceof SyntaxError ? `${file.name} is not valid JSON` : toApiError(err).message)
    }
  }

  async function onExportAll() {
    setActionError(null)
    try {
      const data = await fetchAllScenarios()
      downloadJson(`agentops-scenarios-${new Date().toISOString().slice(0, 10)}.json`, data)
    } catch (err) {
      setActionError(toApiError(err).message)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Scenarios</h1>
          <p className="text-sm text-muted-foreground">
            Versioned logistics test cases with hidden ground truth.
            {total !== undefined ? ` ${total} ${total === 1 ? 'scenario' : 'scenarios'}${hasFilters ? ' match' : ''}.` : ''}
          </p>
        </div>
        {isOwner ? (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => fileInput.current?.click()} disabled={importer.isPending}>
              <Upload aria-hidden /> {importer.isPending ? 'Importing…' : 'Import JSON'}
            </Button>
            <input ref={fileInput} type="file" accept="application/json,.json" className="hidden" onChange={onImportFile} />
            <Button variant="outline" size="sm" onClick={() => void onExportAll()}>
              <Download aria-hidden /> Export all
            </Button>
            <Button size="sm" asChild>
              <Link to="/scenarios/new">
                <FilePlus2 aria-hidden /> New scenario
              </Link>
            </Button>
          </div>
        ) : null}
      </header>

      {actionError ? (
        <Alert variant="destructive">
          <AlertDescription>{actionError}</AlertDescription>
        </Alert>
      ) : null}
      {importResult ? (
        <Alert>
          <AlertTitle>
            Import finished: {importResult.created} created, {importResult.updated} updated,{' '}
            {importResult.unchanged} unchanged, {importResult.errors} failed
          </AlertTitle>
          {importResult.errors ? (
            <AlertDescription>
              <ul className="mt-1 list-disc pl-4">
                {importResult.results
                  .filter((r) => r.outcome === 'error')
                  .map((r, i) => (
                    <li key={i}>
                      <span className="font-mono">{r.scenario_key ?? `item ${i + 1}`}</span>:{' '}
                      {r.errors?.map((e) => `${e.loc}: ${e.msg}`).join('; ')}
                    </li>
                  ))}
              </ul>
            </AlertDescription>
          ) : null}
        </Alert>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-64">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search title or ID"
            aria-label="Search scenarios"
            className="pl-8"
          />
        </div>
        <FilterSelect label="Categories" value={filters.category} options={taxonomy.data?.categories ?? []} onChange={(v) => setFilter('category', v)} />
        <FilterSelect label="Difficulties" value={filters.difficulty} options={taxonomy.data?.difficulties ?? []} onChange={(v) => setFilter('difficulty', v)} />
        <FilterSelect label="Statuses" value={filters.status} options={taxonomy.data?.statuses ?? []} onChange={(v) => setFilter('status', v)} />
        {filters.tag ? (
          <Badge variant="secondary" className="gap-1">
            tag: {filters.tag}
            <button type="button" aria-label="Remove tag filter" onClick={() => setFilter('tag', undefined)}>
              <X className="size-3" />
            </button>
          </Badge>
        ) : null}
        {hasFilters ? (
          <Button variant="ghost" size="sm" onClick={() => { setSearch(''); setParams({}, { replace: true }) }}>
            Clear filters
          </Button>
        ) : null}
      </div>

      {list.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load scenarios</AlertTitle>
          <AlertDescription>{toApiError(list.error).message}</AlertDescription>
        </Alert>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Scenario</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Difficulty</TableHead>
                <TableHead className="text-right">Version</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Tags</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.isPending
                ? Array.from({ length: 6 }, (_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={6}>
                        <Skeleton className="h-8 w-full" />
                      </TableCell>
                    </TableRow>
                  ))
                : rows.map((row) => (
                    <TableRow
                      key={row.id}
                      className="cursor-pointer"
                      onClick={() => navigate(`/scenarios/${row.id}`)}
                    >
                      <TableCell className="max-w-md">
                        <Link to={`/scenarios/${row.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                          {row.title}
                        </Link>
                        <p className="font-mono text-xs text-muted-foreground">{row.scenario_key}</p>
                      </TableCell>
                      <TableCell><CategoryBadge category={row.category} /></TableCell>
                      <TableCell><DifficultyBadge difficulty={row.difficulty} /></TableCell>
                      <TableCell className="text-right tabular-nums">v{row.version}</TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          <StatusBadge status={row.status} />
                          {row.is_locked ? <LockedBadge /> : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {row.tags.map((tag) => (
                            <button
                              key={tag}
                              type="button"
                              onClick={(e) => { e.stopPropagation(); setFilter('tag', tag) }}
                              className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-accent"
                            >
                              {tag}
                            </button>
                          ))}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
              {!list.isPending && rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                    {hasFilters ? 'No scenarios match these filters.' : 'No scenarios yet. Seed the database or import a JSON file.'}
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      )}

      {list.hasNextPage ? (
        <Button variant="outline" className="self-center" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage}>
          {list.isFetchingNextPage ? 'Loading…' : 'Load more'}
        </Button>
      ) : null}
    </div>
  )
}
