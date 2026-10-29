import { useState } from 'react'
import { Link } from 'react-router'
import type { AnsweredAnswer, HedgedAnswer, Person } from '../api/types'
import {
  Breadcrumb,
  ConfidenceMeter,
  HedgedWarning,
  MatchNote,
  PartialHistoryNote,
  SupersededBanner,
} from '../components/answer-parts'
import { AskMaintainerDialog } from '../components/AskMaintainerDialog'
import { ConfidenceFactors } from '../components/ConfidenceFactors'
import { EvidenceChain } from '../components/EvidenceChain'
import { ExplorerPanel } from '../components/ExplorerPanel'
import { GraphNeighbourhood } from '../components/GraphNeighbourhood'
import { PersonCard } from '../components/PersonCard'
import { Badge, Card, SectionLabel } from '../components/ui'
import { entityCrumbs } from '../lib/entity'
import { plural } from '../lib/format'
import { lineagePath } from '../lib/routes'

/**
 * Why Workspace: the whole idea on one screen. Every claim has a source. A hedged answer shows all
 * of it too, but in amber, under a warning, and never looking like a confident one.
 * `asked` is the question as typed.
 */
export function AnsweredView({
  answer,
  repoId,
  asked,
}: {
  answer: AnsweredAnswer | HedgedAnswer
  repoId: string
  asked: string
}) {
  const [asking, setAsking] = useState<Person | null>(null)
  const hedged = answer.verdict === 'hedged'
  const d = answer.decision
  const decidedOn = d.decided_at.slice(0, 10)
  const found = `"${d.summary}" (${d.source.label}, ${decidedOn})`

  return (
    <div className="grid flex-1 grid-cols-1 lg:grid-cols-[232px_minmax(0,1fr)_300px]">
      <aside className="hidden border-r border-line bg-chrome lg:block">
        <ExplorerPanel activeEntity={answer.entity} />
      </aside>

      <article className="min-w-0 px-4 py-6 sm:px-8">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Breadcrumb parts={entityCrumbs(answer.entity)} />
          <Link to={lineagePath(answer.entity.id)} className="text-xs text-blue hover:underline">
            Decision history →
          </Link>
        </div>
        <h1 className="mt-2 text-2xl leading-snug font-semibold">{answer.question}</h1>
        {answer.partial_history && <PartialHistoryNote />}
        <MatchNote answer={answer} asked={asked} />
        {answer.verdict === 'hedged' && <HedgedWarning warning={answer.warning} factors={answer.confidence_factors} />}

        <Card tone={hedged ? 'amber' : 'teal'} className="mt-5 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={d.status === 'ACTIVE' ? 'teal' : 'blue'}>
              {d.status === 'ACTIVE' ? 'Active decision' : 'Partly in force'}
            </Badge>
            {hedged && <Badge tone="amber">Low confidence</Badge>}
            {answer.superseded.length > 0 && (
              <Badge tone="amber">Supersedes {answer.superseded.length} earlier</Badge>
            )}
            <div className="ml-auto">
              <ConfidenceMeter value={answer.confidence} tone={hedged ? 'amber' : 'teal'} thresholds={answer.thresholds} />
            </div>
          </div>
          <p className="mt-3 leading-relaxed">{answer.answer_text}</p>
          <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
            <span>Decided {decidedOn}</span>
            {d.proposed_by && <span>Proposed by @{d.proposed_by}</span>}
            {d.approved_by.length > 0 && <span>Approved by {d.approved_by.map((login) => `@${login}`).join(', ')}</span>}
            {/* A reviewer who also approved is named once, as an approver. */}
            {d.reviewed_by && !d.approved_by.includes(d.reviewed_by) && <span>Reviewed by @{d.reviewed_by}</span>}
            <a href={d.source.url} target="_blank" rel="noreferrer" className="text-blue hover:underline">
              {d.source.label}
            </a>
          </p>
          {d.alternatives.length > 0 && (
            <div className="mt-4 border-t border-line pt-3">
              <SectionLabel>
                <span id="alternatives-heading">Also considered</span>
              </SectionLabel>
              <ul aria-labelledby="alternatives-heading" className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
                {d.alternatives.map((option) => (
                  <li key={option}>{option}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>

        {answer.superseded.map((note) => (
          <SupersededBanner key={note.decision.id} note={note} entityId={answer.entity.id} />
        ))}

        <section className="mt-7" aria-labelledby="chain-heading">
          <div className="flex flex-wrap items-baseline gap-2">
            <h2 id="chain-heading" className="font-semibold">
              Chain of evidence
            </h2>
            <span className="text-xs text-faint">
              {plural(answer.evidence_chain.length, 'source')}. Every claim above is linked to one of them.
            </span>
          </div>
          <div className="mt-3">
            <EvidenceChain steps={answer.evidence_chain} />
          </div>
        </section>
      </article>

      <aside className="space-y-7 border-t border-line bg-chrome p-4 lg:border-t-0 lg:border-l">
        <GraphNeighbourhood nodes={answer.graph.nodes} edges={answer.graph.edges} current={answer.entity} />
        <section>
          <SectionLabel>Who to ask</SectionLabel>
          <div className="mt-3 space-y-2">
            {answer.who_to_ask.map((p) => (
              <PersonCard key={p.login} person={p} onAsk={setAsking} />
            ))}
            {answer.who_to_ask.length === 0 && <p className="text-xs text-faint">No people linked to this decision.</p>}
          </div>
        </section>
        <ConfidenceFactors confidence={answer.confidence} factors={answer.confidence_factors} verdict={answer.verdict} />
      </aside>

      {asking && (
        <AskMaintainerDialog
          person={asking}
          repo={repoId}
          entity={answer.entity}
          question={answer.question}
          finding={
            hedged
              ? `WhyCode found this decision, but with low confidence: ${found}. I'd like to check whether that is the real reason.`
              : `WhyCode found this decision: ${found}. I'd like to confirm it still holds.`
          }
          onClose={() => setAsking(null)}
        />
      )}
    </div>
  )
}
