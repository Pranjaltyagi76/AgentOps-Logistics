import { json } from '@codemirror/lang-json'
import CodeMirror from '@uiw/react-codemirror'
import { ArrowLeft, CheckCircle2, Save } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { toApiError } from '@/lib/api'

import { useSaveScenario, useScenario, useScenarioSource, validateScenario } from './api'
import type { DetailNotice } from './ScenarioDetailPage'
import { NEW_SCENARIO_TEMPLATE } from './template'
import type { ValidationIssue, ValidationReport, WriteResult } from './types'

type Mode = 'create' | 'edit'

const OUTCOME_NOTICE: Record<WriteResult['outcome'], (r: WriteResult) => string> = {
  created: (r) => `Created ${r.scenario.scenario_key} v${r.scenario.version}.`,
  updated: (r) => `Saved v${r.scenario.version}.`,
  new_version: (r) =>
    `The previous version is locked because a run used it, so your edit was saved as v${r.scenario.version}.`,
  unchanged: () => 'No changes to save.',
}

function IssueList({ title, issues, tone }: { title: string; issues: ValidationIssue[]; tone: 'error' | 'warning' }) {
  return (
    <Alert variant={tone === 'error' ? 'destructive' : 'default'}>
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-4">
          {issues.map((issue, i) => (
            <li key={i}>
              <code className="text-xs">{issue.loc}</code>: {issue.msg}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  )
}

function parse(text: string): { value?: unknown; error?: string } {
  try {
    return { value: JSON.parse(text) }
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Invalid JSON' }
  }
}

/** Loads what the form needs, then mounts it with its initial text. */
export function ScenarioEditorPage({ mode }: { mode: Mode }) {
  const { id = '' } = useParams()
  const editing = mode === 'edit'
  const detail = useScenario(id, editing)
  const source = useScenarioSource(id, editing)

  if (!editing) {
    return <EditorForm mode="create" id="" initialText={JSON.stringify(NEW_SCENARIO_TEMPLATE, null, 2)} />
  }
  if (source.isPending || detail.isPending) return <Skeleton className="h-[60vh] w-full" />
  if (source.isError || detail.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{toApiError(source.error ?? detail.error).message}</AlertDescription>
      </Alert>
    )
  }
  return (
    <EditorForm
      key={id}
      mode="edit"
      id={id}
      initialText={JSON.stringify(source.data, null, 2)}
      heading={`Edit ${detail.data.scenario_key} v${detail.data.version}`}
      lockedVersion={detail.data.is_locked ? detail.data.version : undefined}
    />
  )
}

function EditorForm(props: {
  mode: Mode
  id: string
  initialText: string
  heading?: string
  lockedVersion?: number
}) {
  const { mode, id } = props
  const navigate = useNavigate()
  const save = useSaveScenario()

  const [text, setText] = useState(props.initialText)
  const [status, setStatus] = useState<'draft' | 'active'>('active')
  const [report, setReport] = useState<ValidationReport | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [validating, setValidating] = useState(false)

  function readJson(): unknown | undefined {
    const parsed = parse(text)
    setParseError(parsed.error ?? null)
    return parsed.error ? undefined : parsed.value
  }

  async function onValidate() {
    setError(null)
    setReport(null)
    const value = readJson()
    if (value === undefined) return
    setValidating(true)
    try {
      setReport(await validateScenario(value))
    } catch (err) {
      setError(toApiError(err).message)
    } finally {
      setValidating(false)
    }
  }

  async function onSave() {
    setError(null)
    setReport(null)
    const value = readJson()
    if (value === undefined) return
    try {
      const result = await save.mutateAsync({
        id: mode === 'edit' ? id : undefined,
        scenario: value,
        status: mode === 'create' ? status : undefined,
      })
      navigate(`/scenarios/${result.scenario.id}`, {
        state: { notice: OUTCOME_NOTICE[result.outcome](result) } satisfies DetailNotice,
      })
    } catch (err) {
      const apiError = toApiError(err)
      if (apiError.code === 'scenario_invalid') {
        setReport({
          valid: false,
          errors: (apiError.details.errors as ValidationIssue[]) ?? [],
          warnings: (apiError.details.warnings as ValidationIssue[]) ?? [],
        })
      } else {
        setError(apiError.message)
      }
    }
  }

  const backTo = mode === 'edit' ? `/scenarios/${id}` : '/scenarios'

  return (
    <div className="flex flex-col gap-4">
      <Link to={backTo} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> {mode === 'edit' ? 'Back to scenario' : 'Scenarios'}
      </Link>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {props.heading ?? 'New scenario'}
          </h1>
          <p className="text-sm text-muted-foreground">
            Scenario JSON is checked against the schema and the cross-field rules in context/benchmark.md.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {mode === 'create' ? (
            <div className="flex items-center gap-2">
              <Label htmlFor="status" className="text-sm">Status</Label>
              <Select value={status} onValueChange={(v) => setStatus(v as 'draft' | 'active')}>
                <SelectTrigger id="status" className="w-28"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="draft">Draft</SelectItem>
                </SelectContent>
              </Select>
            </div>
          ) : null}
          <Button variant="outline" onClick={() => void onValidate()} disabled={validating}>
            <CheckCircle2 aria-hidden /> {validating ? 'Validating…' : 'Validate'}
          </Button>
          <Button onClick={() => void onSave()} disabled={save.isPending}>
            <Save aria-hidden /> {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </header>

      {props.lockedVersion !== undefined ? (
        <Alert>
          <AlertDescription>
            This version is locked because a run used it. Saving creates v{props.lockedVersion + 1}.
          </AlertDescription>
        </Alert>
      ) : null}
      {parseError ? <IssueList title="Not valid JSON" issues={[{ loc: '(text)', msg: parseError }]} tone="error" /> : null}
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {report?.valid ? (
        <Alert>
          <CheckCircle2 aria-hidden />
          <AlertTitle>Scenario is valid</AlertTitle>
        </Alert>
      ) : null}
      {report && report.errors.length ? (
        <IssueList title={`${report.errors.length} validation error${report.errors.length === 1 ? '' : 's'}`} issues={report.errors} tone="error" />
      ) : null}
      {report && report.warnings.length ? <IssueList title="Warnings" issues={report.warnings} tone="warning" /> : null}

      <div className="overflow-hidden rounded-lg border">
        <CodeMirror
          value={text}
          onChange={setText}
          extensions={[json()]}
          height="65vh"
          basicSetup={{ foldGutter: true, highlightActiveLine: true }}
          aria-label="Scenario JSON"
        />
      </div>
    </div>
  )
}
