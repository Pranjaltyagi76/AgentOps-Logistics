import { ArrowLeft, CheckCircle2, Save } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { toApiError } from '@/lib/api'

import { useAgent, useSaveAgent, useToolNames, validateAgent } from './api'
import { RULE_BASED_PROFILES, type AgentConfig, type AgentWriteResult, type Provider } from './types'

type Issue = { loc: string; msg: string }

const DEFAULTS: AgentConfig = {
  name: '',
  version: 1,
  description: '',
  provider: 'rule_based',
  model_id: 'v1',
  temperature: 0,
  prompt_version: 'agent_system_v1',
  system_prompt: null,
  tools: [],
  max_steps: 8,
  max_tool_calls: 10,
  timeout_s: 60,
  max_retries: 2,
}

const NOTICE: Record<AgentWriteResult['outcome'], (r: AgentWriteResult) => string> = {
  created: (r) => `Created ${r.agent.name} v${r.agent.version}.`,
  updated: (r) => `Saved v${r.agent.version}.`,
  new_version: (r) => `The previous version is locked because a run used it, so this was saved as v${r.agent.version}.`,
  unchanged: () => 'No changes to save.',
}

export function AgentEditorPage({ mode }: { mode: 'create' | 'edit' }) {
  const { id = '' } = useParams()
  const agent = useAgent(id, mode === 'edit')
  const tools = useToolNames()

  if (tools.isPending || (mode === 'edit' && agent.isPending)) return <Skeleton className="h-96 w-full" />
  if (tools.isError || (mode === 'edit' && agent.isError)) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{toApiError(tools.error ?? agent.error).message}</AlertDescription>
      </Alert>
    )
  }
  const initial: AgentConfig =
    mode === 'edit' && agent.data ? agent.data.config : { ...DEFAULTS, tools: tools.data }
  return (
    <AgentForm
      key={id || 'new'}
      mode={mode}
      id={id}
      initial={initial}
      allTools={tools.data}
      lockedVersion={mode === 'edit' && agent.data?.is_locked ? agent.data.version : undefined}
    />
  )
}

function NumberField(props: {
  id: string
  label: string
  value: number
  step?: string
  onChange: (value: number) => void
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={props.id}>{props.label}</Label>
      <Input
        id={props.id}
        type="number"
        step={props.step ?? '1'}
        value={Number.isNaN(props.value) ? '' : props.value}
        onChange={(e) => props.onChange(e.target.valueAsNumber)}
      />
    </div>
  )
}

function AgentForm(props: {
  mode: 'create' | 'edit'
  id: string
  initial: AgentConfig
  allTools: string[]
  lockedVersion?: number
}) {
  const navigate = useNavigate()
  const save = useSaveAgent()
  const [form, setForm] = useState<AgentConfig>(props.initial)
  const [issues, setIssues] = useState<Issue[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [valid, setValid] = useState(false)

  const set = <K extends keyof AgentConfig>(key: K, value: AgentConfig[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setValid(false)
  }
  const payload = (): Partial<AgentConfig> => ({
    ...form,
    description: form.description.trim(),
    system_prompt: form.system_prompt?.trim() ? form.system_prompt : null,
  })

  function setProvider(provider: Provider) {
    setForm((prev) => ({
      ...prev,
      provider,
      model_id: provider === 'rule_based' ? 'v1' : provider === 'gemini' ? 'gemini-flash-latest' : 'gpt-4o-mini',
    }))
  }

  async function onValidate() {
    setError(null)
    try {
      const report = await validateAgent(payload())
      setIssues(report.errors)
      setValid(report.valid)
    } catch (err) {
      setError(toApiError(err).message)
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIssues(null)
    try {
      const result = await save.mutateAsync({ id: props.mode === 'edit' ? props.id : undefined, config: payload() })
      navigate(`/agents/${result.agent.id}`, { state: { notice: NOTICE[result.outcome](result) } })
    } catch (err) {
      const apiError = toApiError(err)
      if (apiError.code === 'agent_invalid') setIssues((apiError.details.errors as Issue[]) ?? [])
      else setError(apiError.message)
    }
  }

  const backTo = props.mode === 'edit' ? `/agents/${props.id}` : '/agents'
  return (
    <form onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-5">
      <Link to={backTo} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> {props.mode === 'edit' ? 'Back to agent' : 'Agents'}
      </Link>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {props.mode === 'edit' ? `Edit ${form.name} v${form.version}` : 'New agent'}
          </h1>
          <p className="text-sm text-muted-foreground">API keys are never part of a config; they stay in the server environment.</p>
        </div>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={() => void onValidate()}>
            <CheckCircle2 aria-hidden /> Validate
          </Button>
          <Button type="submit" disabled={save.isPending}>
            <Save aria-hidden /> {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </header>

      {props.lockedVersion !== undefined ? (
        <Alert><AlertDescription>This version is locked because a run used it. Saving creates v{props.lockedVersion + 1}.</AlertDescription></Alert>
      ) : null}
      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      {valid ? <Alert><CheckCircle2 aria-hidden /><AlertTitle>Config is valid</AlertTitle></Alert> : null}
      {issues && issues.length ? (
        <Alert variant="destructive">
          <AlertTitle>{issues.length} problem{issues.length === 1 ? '' : 's'}</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {issues.map((issue, i) => (
                <li key={i}><code className="text-xs">{issue.loc}</code>: {issue.msg}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader><CardTitle className="text-base">Identity and model</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              value={form.name}
              disabled={props.mode === 'edit'}
              placeholder="my-agent"
              onChange={(e) => set('name', e.target.value)}
            />
            <p className="text-xs text-muted-foreground">Lower-case letters, digits and dashes. Cannot change later.</p>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="provider">Provider</Label>
            <Select value={form.provider} onValueChange={(v) => setProvider(v as Provider)}>
              <SelectTrigger id="provider"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="rule_based">Rule-based (no LLM)</SelectItem>
                <SelectItem value="gemini">Google Gemini (Phase 6)</SelectItem>
                <SelectItem value="openai">OpenAI (later)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="model">{form.provider === 'rule_based' ? 'Profile' : 'Model ID'}</Label>
            {form.provider === 'rule_based' ? (
              <Select value={form.model_id} onValueChange={(v) => set('model_id', v)}>
                <SelectTrigger id="model"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {RULE_BASED_PROFILES.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
                </SelectContent>
              </Select>
            ) : (
              <Input id="model" value={form.model_id} onChange={(e) => set('model_id', e.target.value)} />
            )}
          </div>
          <NumberField id="temperature" label="Temperature" step="0.1" value={form.temperature} onChange={(v) => set('temperature', v)} />
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label htmlFor="description">Description</Label>
            <Textarea id="description" rows={2} value={form.description} onChange={(e) => set('description', e.target.value)} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Limits</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-4">
          <NumberField id="max_steps" label="Max steps (1–20)" value={form.max_steps} onChange={(v) => set('max_steps', v)} />
          <NumberField id="max_tool_calls" label="Max tool calls (1–30)" value={form.max_tool_calls} onChange={(v) => set('max_tool_calls', v)} />
          <NumberField id="timeout_s" label="Timeout, s (5–300)" value={form.timeout_s} onChange={(v) => set('timeout_s', v)} />
          <NumberField id="max_retries" label="Model retries (0–5)" value={form.max_retries} onChange={(v) => set('max_retries', v)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Tools</CardTitle></CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-2">
          {props.allTools.map((tool) => (
            <label key={tool} className="flex items-center gap-2 text-sm">
              <Checkbox
                aria-label={tool}
                checked={form.tools.includes(tool)}
                onCheckedChange={(checked) =>
                  set('tools', checked === true ? [...form.tools, tool] : form.tools.filter((t) => t !== tool))
                }
              />
              <span className="font-mono">{tool}</span>
            </label>
          ))}
          <p className="text-xs text-muted-foreground sm:col-span-2">
            The agent can use a tool only if it is listed here and the scenario makes it available.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">System prompt</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex max-w-sm flex-col gap-1.5">
            <Label htmlFor="prompt_version">Prompt version</Label>
            <Input id="prompt_version" value={form.prompt_version} onChange={(e) => set('prompt_version', e.target.value)} />
          </div>
          <Textarea
            aria-label="System prompt"
            rows={12}
            className="font-mono text-xs"
            placeholder="Leave empty to use the prompt file for this prompt version."
            value={form.system_prompt ?? ''}
            onChange={(e) => set('system_prompt', e.target.value)}
          />
        </CardContent>
      </Card>
    </form>
  )
}
