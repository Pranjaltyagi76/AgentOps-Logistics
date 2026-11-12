import { Gavel } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { toApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/format'

import { useRunJudge } from './api'
import type { Evaluation } from './types'

/** Advisory LLM judge (tone, clarity, grounding). Never part of the score or verdict. */
export function JudgePanel({ runId, evaluation }: { runId: string; evaluation: Evaluation }) {
  const run = useRunJudge(runId)
  const judge = evaluation.judge
  if (!judge && !evaluation.judge_available) return null

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <CardTitle className="flex items-center gap-2 text-base">
            <Gavel className="size-4" aria-hidden /> LLM judge <Badge variant="outline">advisory</Badge>
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            A second opinion on tone, clarity and grounding. It is not part of the score or the verdict, and it
            is not yet calibrated against hand-labelled replies.
          </p>
        </div>
        {evaluation.judge_available ? (
          <Button variant="outline" size="sm" disabled={run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? 'Judging…' : judge ? 'Run judge again' : 'Run judge'}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        {run.error ? (
          <Alert variant="destructive"><AlertDescription>{toApiError(run.error).message}</AlertDescription></Alert>
        ) : null}
        {judge ? (
          <>
            <p>
              <span className="text-2xl font-semibold tabular-nums">{judge.score.toFixed(2)}</span>
              <span className="text-muted-foreground"> / 1 · uncertainty {judge.uncertainty}</span>
            </p>
            {judge.rationale ? <p>{judge.rationale}</p> : null}
            {judge.evidence_refs?.length ? (
              <p className="font-mono text-xs text-muted-foreground">relied on {judge.evidence_refs.join(', ')}</p>
            ) : null}
            <p className="text-xs text-muted-foreground">
              {judge.judge_model} · {judge.prompt_version} · {formatDateTime(judge.created_at)}
            </p>
          </>
        ) : (
          <p className="text-muted-foreground">Not judged yet. Each run of the judge uses the free Gemini quota.</p>
        )}
      </CardContent>
    </Card>
  )
}
