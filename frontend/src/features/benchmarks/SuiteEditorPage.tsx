import { ArrowLeft, Save } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { useScenarioList } from '@/features/scenarios/api'
import { toApiError } from '@/lib/api'

import { useSaveSuite, useSuite } from './api'
import type { Suite } from './types'

/** Owner: create or edit a suite by ticking scenarios or naming a tag. */
export function SuiteEditorPage({ mode }: { mode: 'create' | 'edit' }) {
  const { id } = useParams()
  const existing = useSuite(mode === 'edit' ? id : undefined)
  if (mode === 'edit' && existing.isPending) return <Skeleton className="h-64 w-full" />
  if (mode === 'edit' && existing.isError) {
    return <Alert variant="destructive"><AlertDescription>{toApiError(existing.error).message}</AlertDescription></Alert>
  }
  return <SuiteForm mode={mode} initial={existing.data} />
}

function SuiteForm({ mode, initial }: { mode: 'create' | 'edit'; initial?: Suite }) {
  const navigate = useNavigate()
  const scenarios = useScenarioList({ status: 'active' })
  const save = useSaveSuite(initial?.id)
  const [name, setName] = useState(initial?.name ?? '')
  const [title, setTitle] = useState(initial?.title ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [byTag, setByTag] = useState(initial ? initial.tag !== null : false)
  const [tag, setTag] = useState(initial?.tag ?? '')
  const [keys, setKeys] = useState<string[]>(initial?.scenario_keys ?? [])
  const [error, setError] = useState<string | null>(null)

  const rows = scenarios.data?.pages.flatMap((p) => p.items) ?? []
  const tags = [...new Set(rows.flatMap((r) => r.tags))].sort()

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      const suite = await save.mutateAsync({
        name,
        title,
        description,
        ...(byTag ? { tag, scenario_keys: null } : { scenario_keys: keys, tag: null }),
      })
      navigate('/suites', { state: { saved: suite.id } })
    } catch (err) {
      setError(toApiError(err).message)
    }
  }

  if (scenarios.isPending) return <Skeleton className="h-64 w-full" />

  return (
    <form onSubmit={(e) => void onSubmit(e)} className="mx-auto flex max-w-3xl flex-col gap-6">
      <Link to="/suites" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> Benchmarks
      </Link>
      <h1 className="text-2xl font-semibold tracking-tight">{mode === 'create' ? 'New suite' : `Edit ${name}`}</h1>
      <Card>
        <CardContent className="flex flex-col gap-4 pt-6">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="name">Name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} disabled={mode === 'edit'}
                   placeholder="lowercase-with-dashes" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="title">Title</Label>
            <Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="description">Description</Label>
            <Textarea id="description" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-base">Scenarios</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={byTag} onCheckedChange={(v) => setByTag(v === true)} aria-label="Select scenarios by tag" />
            Select scenarios by tag (new scenarios with the tag join automatically)
          </label>
          {byTag ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="tag">Tag</Label>
              <Input id="tag" value={tag} onChange={(e) => setTag(e.target.value)} list="suite-tags" />
              <datalist id="suite-tags">{tags.map((t) => <option key={t} value={t} />)}</datalist>
              <p className="text-xs text-muted-foreground">
                Matches {rows.filter((r) => r.tags.includes(tag)).length} active scenario(s).
              </p>
            </div>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {rows.map((r) => (
                <li key={r.scenario_key}>
                  <label className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={keys.includes(r.scenario_key)}
                      onCheckedChange={(v) =>
                        setKeys((prev) => (v === true ? [...prev, r.scenario_key] : prev.filter((k) => k !== r.scenario_key)))
                      }
                      aria-label={r.scenario_key}
                    />
                    <span className="font-mono text-xs">{r.scenario_key}</span>
                    <span className="text-muted-foreground">{r.title}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      <Button type="submit" className="self-start" disabled={save.isPending || !name || !title || (byTag ? !tag : !keys.length)}>
        <Save aria-hidden /> {save.isPending ? 'Saving…' : 'Save suite'}
      </Button>
    </form>
  )
}
